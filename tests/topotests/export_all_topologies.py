#!/usr/bin/env python3
# SPDX-License-Identifier: ISC
#
# export_all_topologies.py
# Batch export all topologies to JSON
#

"""
Script to batch export all topologies in topotests to JSON files.
Each test directory will get an exported_topology.json file.
"""

import sys
import os
import json
import importlib.util
from pathlib import Path
import argparse

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.topogen import Topogen
from lib.export_topo_to_json import export_topology_to_json


def find_build_topo_function(test_dir):
    """
    Find and return the build_topo function from test files.
    """
    for filename in os.listdir(test_dir):
        if filename.startswith('test_') and filename.endswith('.py'):
            test_file = os.path.join(test_dir, filename)
            
            try:
                spec = importlib.util.spec_from_file_location("test_module", test_file)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    
                    # Look for build_topo function
                    if hasattr(module, 'build_topo'):
                        return module.build_topo, test_file
                    
                    # Try other patterns
                    for attr_name in dir(module):
                        if 'build' in attr_name.lower() and 'topo' in attr_name.lower():
                            attr = getattr(module, attr_name)
                            if callable(attr):
                                return attr, test_file
            except:
                continue
    
    return None, None


def export_single_directory(test_dir, verbose=False):
    """
    Export topology from a single test directory.
    Returns: (success, error_message)
    """
    test_name = os.path.basename(test_dir)
    
    # Find build function
    build_func, test_file = find_build_topo_function(test_dir)
    
    if build_func is None:
        return False, "No build_topo function found"
    
    # Create Topogen instance
    try:
        tgen = Topogen(build_func, test_name)
    except Exception as e:
        return False, f"Error creating topology: {str(e)}"
    
    # Export to JSON
    output_path = os.path.join(test_dir, 'exported_topology.json')
    try:
        topo_data = export_topology_to_json(tgen, output_path)
        
        if verbose:
            routers = len(topo_data.get('routers', {}))
            switches = len(topo_data.get('switches', {}))
            return True, f"OK (R:{routers} S:{switches})"
        else:
            return True, "OK"
    except Exception as e:
        return False, f"Export error: {str(e)}"


def find_all_test_directories(topotests_dir):
    """
    Find all test directories in topotests.
    Returns list of directory paths.
    """
    test_dirs = []
    
    for entry in os.listdir(topotests_dir):
        full_path = os.path.join(topotests_dir, entry)
        
        # Skip if not a directory
        if not os.path.isdir(full_path):
            continue
        
        # Skip special directories
        if entry in ['lib', 'munet', 'docker', '__pycache__', '.git']:
            continue
        
        # Check if it contains test_*.py files
        has_test_file = any(
            f.startswith('test_') and f.endswith('.py')
            for f in os.listdir(full_path)
        )
        
        if has_test_file:
            test_dirs.append(full_path)
    
    return sorted(test_dirs)


def main():
    parser = argparse.ArgumentParser(
        description='Batch export all topologies to JSON'
    )
    parser.add_argument(
        '--test-dirs',
        help='Comma-separated list of specific test directories to export',
        default=None
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed output including router/switch counts'
    )
    parser.add_argument(
        '--output-summary',
        help='Path to save summary JSON file',
        default=None
    )
    
    args = parser.parse_args()
    
    # Get topotests directory
    topotests_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Find test directories
    if args.test_dirs:
        # Specific directories requested
        test_names = [d.strip() for d in args.test_dirs.split(',')]
        test_dirs = [os.path.join(topotests_dir, name) for name in test_names]
        
        # Validate they exist
        test_dirs = [d for d in test_dirs if os.path.isdir(d)]
    else:
        # All directories
        test_dirs = find_all_test_directories(topotests_dir)
    
    print(f"Found {len(test_dirs)} test directories to process")
    print("="*60)
    
    # Process each directory
    results = {
        'success': [],
        'failed': []
    }
    
    for i, test_dir in enumerate(test_dirs, 1):
        test_name = os.path.basename(test_dir)
        
        print(f"[{i}/{len(test_dirs)}] {test_name}...", end=' ', flush=True)
        
        success, message = export_single_directory(test_dir, verbose=args.verbose)
        
        if success:
            print(f"✓ {message}")
            results['success'].append({
                'name': test_name,
                'path': test_dir,
                'output': os.path.join(test_dir, 'exported_topology.json')
            })
        else:
            print(f"✗ {message}")
            results['failed'].append({
                'name': test_name,
                'path': test_dir,
                'error': message
            })
    
    print("="*60)
    print(f"\nResults:")
    print(f"  Successful: {len(results['success'])}")
    print(f"  Failed:     {len(results['failed'])}")
    print(f"  Total:      {len(test_dirs)}")
    
    # Show failed tests
    if results['failed']:
        print(f"\nFailed tests:")
        for item in results['failed'][:10]:  # Show first 10
            print(f"  - {item['name']}: {item['error']}")
        
        if len(results['failed']) > 10:
            print(f"  ... and {len(results['failed']) - 10} more")
    
    # Save summary if requested
    if args.output_summary:
        with open(args.output_summary, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\nSummary saved to: {args.output_summary}")
    
    # Exit code based on results
    if results['success']:
        print(f"\n✓ Export completed ({len(results['success'])} topologies exported)")
        sys.exit(0)
    else:
        print(f"\n✗ All exports failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
