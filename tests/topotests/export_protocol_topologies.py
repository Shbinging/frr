#!/usr/bin/env python3
# SPDX-License-Identifier: ISC
#
# export_protocol_topologies.py
#
# Dedicated script to export topologies for OSPF, BABEL, ISIS, and RIP.
# Enforces strict success requirements and exports to a central directory.
#

import sys
import os
import json
import importlib.util
import argparse
import unittest.mock
import shutil
from collections import OrderedDict

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import our library
try:
    from lib.export_topo_to_json import export_topology_to_json
except ImportError:
    # Handle case where we run from inside topotests dir
    sys.path.insert(0, os.getcwd())
    from lib.export_topo_to_json import export_topology_to_json

# -------------------------------------------------------------------------
# MOCKING INFRASTRUCTURE (Copied & Enhanced from dynamic_export_topologies.py)
# -------------------------------------------------------------------------

class MockMininet:
    def __init__(self, *args, **kwargs):
        self.cfgopt = {}
        self.links = []
        self.net = self
    def __getattr__(self, name):
        return unittest.mock.MagicMock()
    def __getitem__(self, key):
        return unittest.mock.MagicMock()

class MockCommander:
    def __init__(self, *args, **kwargs): pass
    def get_exec_path(self, cmd): return "/usr/bin/" + cmd
    def cmd_status(self, cmd, warn=False): return (0, "Topotest Mock", "")

def mock_get_logger(name, log_level="debug", target=None):
    return unittest.mock.MagicMock()

def mock_fix_host_limits(): pass
def mock_fix_netns_limits(net): pass
def mock_module_present(mod): return True

def mock_check_call(args, shell=False, **kwargs):
    # If it's a mkdir command, execute it to ensure directories exist
    cmd = args
    if isinstance(cmd, list):
        cmd = " ".join(cmd)
    
    if "mkdir" in cmd:
        # Extract path roughly or just ignore errors if we can't parse
        # But Topogen uses: "mkdir -p {0} && chmod 1777 {0}"
        if "mkdir -p" in cmd:
            parts = cmd.split()
            for i, part in enumerate(parts):
                if part == "-p" and i + 1 < len(parts):
                    path = parts[i+1]
                    # path might be followed by &&
                    if path == "&&": continue 
                    
                    # Clean path
                    path = path.split('&&')[0].strip()
                    
                    try:
                        os.makedirs(path, exist_ok=True)
                    except:
                        pass
    pass

def mock_chown(*args, **kwargs): pass
def mock_chmod(*args, **kwargs): pass
def mock_grp_getgrnam(name): return (0, 0, 0)

# Mocks setup
import lib.topotest
import lib.topogen
import lib.topolog
import lib.micronet

lib.topotest.fix_host_limits = mock_fix_host_limits
lib.topotest.fix_netns_limits = mock_fix_netns_limits
lib.topotest.module_present = mock_module_present

class MockPytestOption:
    def __init__(self):
        self.rundir = "/tmp/topotests_export_logs"

class MockPytestConfig:
    def __init__(self):
        self.option = MockPytestOption()
    def getoption(self, name, default=None):
        if name == "capture": return "no"
        if name == "rundir": return "/tmp/topotests_export_logs"
        return default
    def getini(self, name): return None

sys.modules['pytest'] = unittest.mock.MagicMock()
config_mock = MockPytestConfig()

lib.topotest.pytest = unittest.mock.MagicMock()
lib.topotest.pytestconfig = config_mock
lib.topotest.g_pytest_config = config_mock

MOCK_LOG_DIR = "/tmp/topotests_mock_logs"
if not os.path.exists(MOCK_LOG_DIR):
    os.makedirs(MOCK_LOG_DIR, exist_ok=True)

lib.topotest.get_logs_path = lambda x: MOCK_LOG_DIR
lib.topogen.pytest = unittest.mock.MagicMock()
lib.topogen.pytestconfig = config_mock
lib.topolog.is_xdist_controller = lambda: False
lib.topogen.Mininet = MockMininet
lib.topogen.subprocess.check_call = mock_check_call
lib.topogen.os.chown = mock_chown
lib.topogen.os.chmod = mock_chmod
lib.topogen.grp.getgrnam = mock_grp_getgrnam
lib.micronet.Commander = MockCommander
lib.topolog.get_logger = mock_get_logger

# -------------------------------------------------------------------------
# EXPORT LOGIC
# -------------------------------------------------------------------------

TARGET_PROTOCOLS = ['ospf', 'babel', 'isis', 'rip']

def process_test_file(test_file):
    test_dir = os.path.dirname(test_file)
    test_name = os.path.basename(test_dir)
    module_name = os.path.basename(test_file).replace('.py', '')

    # Try to clean up previous modules to avoid conflicts
    if module_name in sys.modules:
        del sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(module_name, test_file)
    if not spec or not spec.loader:
        return None, "Could not load module spec"
    
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        return None, f"Module execution failed: {e}"

    build_func = None
    if hasattr(module, 'build_topo'):
        build_func = module.build_topo
    else:
        for attr_name in dir(module):
            if 'build' in attr_name.lower() and 'topo' in attr_name.lower():
                attr = getattr(module, attr_name)
                if callable(attr):
                    # Check if it has 'tgen' in args or looks like a builder
                    build_func = attr
                    break
    
    # If no build_topo, try to run setup_module
    if not build_func:
        if hasattr(module, 'setup_module'):
            class TopologyCaptured(Exception):
                pass

            try:
                # Intercept Topogen creation
                captured_tgen = []
                original_init = lib.topogen.Topogen.__init__
                
                def side_effect_init(self, topodef, modname="unnamed"):
                    # Call original init to build the topology
                    original_init(self, topodef, modname)
                    captured_tgen.append(self)
                    # Abort setup_module execution immediately!
                    raise TopologyCaptured()
                
                with unittest.mock.patch('lib.topogen.Topogen.__init__', side_effect=side_effect_init, autospec=True):
                    try:
                        module.setup_module(module)
                    except TopologyCaptured:
                        pass
                    except Exception as e:
                        # Only report if not our custom exception (in case it was wrapped)
                        pass
                    
                if captured_tgen:
                    tgen = captured_tgen[-1]
                    return export_topology_to_json(tgen, None), None
                else:
                    return None, "setup_module ran but no Topogen created"
                    
            except Exception as e:
                return None, f"setup_module execution failed: {e}"
        
        # Fallback: check for pytest fixtures 'tgen' or '_tgen'
        if 'ospf_clientapi' in module_name or 'rip_bfd' in module_name:
             print(f"DEBUG: Processing {module_name}. Dir: {dir(module)}")
             if hasattr(module, '_tgen'):
                 print("DEBUG: Found _tgen")
             if hasattr(module, 'tgen'):
                 print("DEBUG: Found tgen")
                 
        fixture_func = getattr(module, 'tgen', getattr(module, '_tgen', None))
        if fixture_func and callable(fixture_func):
            import inspect
            class TopologyCaptured(Exception): pass
            
            try:
                captured_tgen = []
                original_init = lib.topogen.Topogen.__init__
                
                def side_effect_init(self, topodef, modname="unnamed"):
                    original_init(self, topodef, modname)
                    captured_tgen.append(self)
                    raise TopologyCaptured()
                
                # Mock Request object
                class MockRequest:
                    def __init__(self, mod):
                        self.module = mod
                        self.param = 4 # Default for ospf_clientapi and others
                
                req = MockRequest(module)
                
                with unittest.mock.patch('lib.topogen.Topogen.__init__', side_effect=side_effect_init, autospec=True):
                    try:
                        # Call fixture
                        res = fixture_func(req)
                        # If generator, advance it
                        if inspect.isgenerator(res):
                            next(res)
                    except TopologyCaptured:
                        pass
                    except Exception:
                        pass
                
                if captured_tgen:
                    tgen = captured_tgen[-1]
                    return export_topology_to_json(tgen, None), None
                
            except Exception as e:
                 return None, f"Fixture execution failed: {e}"

        return None, "No build_topo variable, setup_module, or tgen fixture found"

    try:
        tgen = lib.topogen.Topogen(build_func, test_name)
        return export_topology_to_json(tgen, output_path=None), None
        
    except Exception as e:
        return None, f"Topology build failed: {e}"

def main():
    parser = argparse.ArgumentParser(description='Export OSPF/BABEL/ISIS/RIP topologies')
    parser.add_argument('--output-dir', default='collected_topologies', help='Directory to save JSON files')
    parser.add_argument('--verbose', '-v', action='store_true')
    args = parser.parse_args()

    topotests_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.abspath(args.output_dir)
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    print(f"Destination: {output_dir}")
    
    # Find files
    target_files = []
    for root, dirs, files in os.walk(topotests_dir):
        if 'lib' in root.split(os.sep) or 'munet' in root.split(os.sep):
            continue
            
        for f in files:
            if f.startswith('test_') and f.endswith('.py'):
                full_path = os.path.join(root, f)
                # Check if it matches target protocols
                if any(p in f.lower() or p in root.lower() for p in TARGET_PROTOCOLS):
                    target_files.append(full_path)
    
    target_files = sorted(target_files)
    print(f"Found {len(target_files)} relevant tests.")
    
    success_count = 0
    fail_count = 0
    failures = []
    
    for i, fpath in enumerate(target_files, 1):
        rel_path = os.path.relpath(fpath, topotests_dir)
        test_dir_name = os.path.basename(os.path.dirname(fpath))
        module_name = os.path.basename(fpath).replace('.py', '')
        if module_name.startswith('test_'):
            clean_name = module_name[5:]
        else:
            clean_name = module_name
        
        # Output filename: based on file name to avoid collisions in same directory
        json_filename = f"{clean_name}.json"
        json_path = os.path.join(output_dir, json_filename)
        
        print(f"[{i:3d}/{len(target_files)}] {clean_name:35s}", end='', flush=True)
        
        topo_data, error = process_test_file(fpath)
        
        if topo_data:
            # Check if empty
            if not topo_data:
                 print(f" ⚠ Empty Topology", end='')
            
            with open(json_path, 'w') as f:
                json.dump(topo_data, f, indent=2)
                
            r_count = len(topo_data)
            s_count = sum(len(s) for s in topo_data.values())
            print(f" ✓ R:{r_count} S_Links:{s_count}")
            success_count += 1
        else:
            print(f" ✗ {error}")
            fail_count += 1
            failures.append(f"{test_dir_name}: {error}")

    print("\n" + "="*60)
    print(f"Success: {success_count}")
    print(f"Failed:  {fail_count}")
    print("="*60)
    
    if failures:
        print("\nFailures details:")
        for f in failures:
            print(f"- {f}")
        sys.exit(1) # Exit with error code if any failure
    else:
        print("\nAll target protocols exported successfully!")

if __name__ == "__main__":
    main()
