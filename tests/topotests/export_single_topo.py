#!/usr/bin/env python3
# SPDX-License-Identifier: ISC
#
# export_single_topo.py
# Export a single topology to JSON
#

"""
Script to export a single topology from a test directory.
Usage: python3 export_single_topo.py <test_directory>
"""

import sys
import os
import json
import importlib.util

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.topogen import Topogen
from lib.export_topo_to_json import export_topology_to_json, print_topology_summary


def find_build_topo_function(test_dir):
    """
    Find and return the build_topo function from test files.
    
    Args:
        test_dir: Path to test directory
        
    Returns:
        Tuple of (build_function, test_file_path) or (None, None)
    """
    # Look for test_*.py files
    for filename in os.listdir(test_dir):
        if filename.startswith('test_') and filename.endswith('.py'):
            test_file = os.path.join(test_dir, filename)
            
            # Try to import the module
            try:
                spec = importlib.util.spec_from_file_location("test_module", test_file)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    
                    # Look for build_topo function
                    if hasattr(module, 'build_topo'):
                        return module.build_topo, test_file
                    
                    # Some tests might have different patterns
                    for attr_name in dir(module):
                        if 'build' in attr_name.lower() and 'topo' in attr_name.lower():
                            attr = getattr(module, attr_name)
                            if callable(attr):
                                return attr, test_file
            except Exception as e:
                print(f"Warning: Could not import {filename}: {e}")
                continue
    
    return None, None


def export_single_topology(test_dir):
    """
    Export topology from a single test directory.
    
    Args:
        test_dir: Path to test directory
        
    Returns:
        True if successful, False otherwise
    """
    test_dir = os.path.abspath(test_dir)
    test_name = os.path.basename(test_dir)
    
    print(f"Processing: {test_name}")
    print(f"Directory: {test_dir}")
    
    # Check if directory exists
    if not os.path.isdir(test_dir):
        print(f"Error: Directory not found: {test_dir}")
        return False
    
    # Find build function
    build_func, test_file = find_build_topo_function(test_dir)
    
    if build_func is None:
        print(f"Error: Could not find build_topo function in {test_dir}")
        return False
    
    print(f"Found build function in: {os.path.basename(test_file)}")
    
    # Create Topogen instance
    try:
        tgen = Topogen(build_func, test_name)
        print(f"Topology created successfully")
    except Exception as e:
        print(f"Error creating topology: {e}")
        return False
    
    # Export to JSON
    output_path = os.path.join(test_dir, 'exported_topology.json')
    try:
        topo_data = export_topology_to_json(tgen, output_path)
        print(f"Exported to: {output_path}")
        
        # Print summary
        print_topology_summary(topo_data)
        
        return True
    except Exception as e:
        print(f"Error exporting topology: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 export_single_topo.py <test_directory>")
        print("Example: python3 export_single_topo.py ospf_topo1")
        sys.exit(1)
    
    test_dir = sys.argv[1]
    
    # If relative path, make it relative to topotests directory
    if not os.path.isabs(test_dir):
        topotests_dir = os.path.dirname(os.path.abspath(__file__))
        test_dir = os.path.join(topotests_dir, test_dir)
    
    success = export_single_topology(test_dir)
    
    if success:
        print("\n✓ Export completed successfully")
        sys.exit(0)
    else:
        print("\n✗ Export failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
