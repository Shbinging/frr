#!/usr/bin/env python3
# SPDX-License-Identifier: ISC
#
# dynamic_export_topologies.py
#
# Dynamic topology exporter that runs build_topo() with mocked system calls.
# This allows extracting the exact topology structure as defined by Python code
# without needing root privileges or Mininet installation.
#

import sys
import os
import json
import importlib.util
import argparse
import unittest.mock
from collections import OrderedDict

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import our export utility
from lib.export_topo_to_json import export_topology_to_json

# -------------------------------------------------------------------------
# MOCKING INFRASTRUCTURE
# -------------------------------------------------------------------------

class MockMininet:
    def __init__(self, *args, **kwargs):
        self.cfgopt = {}
        self.links = []
        self.net = self # Mock net inside mininet if needed
        
    def __getattr__(self, name):
        # Return a MagicMock for any undefined attribute/method
        return unittest.mock.MagicMock()

    def __getitem__(self, key):
        # Return a MagicMock for any item access
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
def mock_check_call(*args, **kwargs): pass
def mock_chown(*args, **kwargs): pass
def mock_chmod(*args, **kwargs): pass
def mock_grp_getgrnam(name): return (0, 0, 0)

# Apply mocks to lib.topotest and lib.topogen
import lib.topotest
import lib.topogen
import lib.topolog
import lib.micronet

# Patch lib.topotest functions
lib.topotest.fix_host_limits = mock_fix_host_limits
lib.topotest.fix_netns_limits = mock_fix_netns_limits
lib.topotest.module_present = mock_module_present

# Mocking pytest execution environment
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

# Mock pytest module if it needs to be imported
sys.modules['pytest'] = unittest.mock.MagicMock()
# Inject config into helper modules if they look for it
# (We can't easily inject into already imported modules without reloading, 
#  so we rely on patching where it's used)

# Create a config instance
config_mock = MockPytestConfig()

# Patch topotest's pytest usage if any
lib.topotest.pytest = unittest.mock.MagicMock()
lib.topotest.pytestconfig = config_mock
lib.topotest.g_pytest_config = config_mock

# Ensure mock log directory exists
MOCK_LOG_DIR = "/tmp/topotests_mock_logs"
if not os.path.exists(MOCK_LOG_DIR):
    os.makedirs(MOCK_LOG_DIR)

# Patch topotest.get_logs_path to avoid dependency on config if possible, 
# or just ensure it works with the mock
lib.topotest.get_logs_path = lambda x: MOCK_LOG_DIR

# Patch topogen's pytest usage
lib.topogen.pytest = unittest.mock.MagicMock()
lib.topogen.pytestconfig = config_mock

# Patch topolog xdist check
lib.topolog.is_xdist_controller = lambda: False


# Patch lib.topolog
lib.topolog.get_logger = mock_get_logger

# Patch lib.micronet
lib.micronet.Commander = MockCommander

# Patch Mininet in lib.topogen (it imports it as Mininet)
# We need to find where Mininet is imported in topogen
lib.topogen.Mininet = MockMininet

# Patch subprocess/os calls in topogen
lib.topogen.subprocess.check_call = mock_check_call
lib.topogen.os.chown = mock_chown
lib.topogen.os.chmod = mock_chmod
lib.topogen.grp.getgrnam = mock_grp_getgrnam

# -------------------------------------------------------------------------
# EXPORT LOGIC
# -------------------------------------------------------------------------

def process_test_file(test_file):
    """
    Dynamically import and process a test file to extract topology.
    """
    test_dir = os.path.dirname(test_file)
    test_name = os.path.basename(test_dir)
    module_name = os.path.basename(test_file).replace('.py', '')
    
    # Reload topogen to ensure clean state if needed (though we use fresh instances)
    # But module imports might be cached.
    
    spec = importlib.util.spec_from_file_location(module_name, test_file)
    if not spec or not spec.loader:
        return None, "Could not load module spec"
        
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        return None, f"Module execution failed: {e}"

    # Find build function
    build_func = None
    if hasattr(module, 'build_topo'):
        build_func = module.build_topo
    else:
        # Fallback search
        for attr_name in dir(module):
            if 'build' in attr_name.lower() and 'topo' in attr_name.lower():
                attr = getattr(module, attr_name)
                if callable(attr):
                    build_func = attr
                    break
    
    if not build_func:
        return None, "No build_topo function found"

    # Create Topogen instance (WITH MOCKS ACTIVE)
    try:
        # Some tests expect 'spytest' or specific logging in setup
        tgen = lib.topogen.Topogen(build_func, test_name)
        
        # Now tgen.gears should be populated!
        
        # Export
        output_path = os.path.join(test_dir, 'exported_topology.json')
        result = export_topology_to_json(tgen, output_path)
        
        return result, None
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return None, f"Topology build failed: {e}"

def find_test_files(topotests_dir):
    """Find all test files."""
    test_files = []
    for root, dirs, files in os.walk(topotests_dir):
        # Skip special dirs
        if 'lib' in root.split(os.sep) or 'munet' in root.split(os.sep):
            continue
            
        for f in files:
            if f.startswith('test_') and f.endswith('.py'):
                test_files.append(os.path.join(root, f))
    return sorted(test_files)

def main():
    parser = argparse.ArgumentParser(description='Dynamic Topology Exporter')
    parser.add_argument('--test-dirs', help='Specific directories to process')
    parser.add_argument('--limit', type=int, help='Limit number of tests')
    parser.add_argument('--verbose', '-v', action='store_true')
    args = parser.parse_args()

    topotests_dir = os.path.dirname(os.path.abspath(__file__))
    
    all_test_files = find_test_files(topotests_dir)
    
    # Filter
    if args.test_dirs:
        targets = args.test_dirs.split(',')
        all_test_files = [f for f in all_test_files if any(t in f for t in targets)]
    
    if args.limit:
        all_test_files = all_test_files[:args.limit]
        
    print(f"Dynamically processing {len(all_test_files)} tests...")
    print("="*60)
    
    success_count = 0
    fail_count = 0 
    
    results = {'success': [], 'failed': []}

    for i, fpath in enumerate(all_test_files, 1):
        rel_path = os.path.relpath(fpath, topotests_dir)
        test_dir = os.path.dirname(fpath)
        test_dir_name = os.path.basename(test_dir)
        
        print(f"[{i}/{len(all_test_files)}] {test_dir_name:30s}", end=' ', flush=True)
        
        topo_data, error = process_test_file(fpath)
        
        if topo_data:
            r_count = len(topo_data)
            s_count = sum(len(s) for s in topo_data.values())
            print(f"✓ R:{r_count} S_Links:{s_count}")
            success_count += 1
            results['success'].append({'path': rel_path, 'r': r_count, 's_links': s_count})
        else:
            print(f"✗ {error}")
            fail_count += 1
            results['failed'].append({'path': rel_path, 'error': error})

    print("="*60)
    print(f"Success: {success_count}")
    print(f"Failed:  {fail_count}")
    
    # Save summary
    with open('dynamic_export_summary.json', 'w') as f:
        json.dump(results, f, indent=2)

if __name__ == "__main__":
    main()
