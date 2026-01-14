#!/usr/bin/env python3
# SPDX-License-Identifier: ISC
#
# batch_export_topologies.py
# Simple batch export of all topologies using regex parsing
#

"""
Simplified batch export script that extracts topology structure from
Python test files using regex pattern matching. Outputs JSON files with
router and switch connection information.
"""

import os
import re
import json
from collections import OrderedDict
import argparse


def extract_topology_from_file(filepath):
    """
    Extract topology information from a test file using regex.
    
    Returns:
        Dictionary with routers and switches, or None if parsing fails
    """
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except:
        return None
    
    # Find the build_topo function
    func_pattern = r'def\s+(build_?topo\w*)\s*\([^)]*\):\s*(.*?)(?=\ndef\s+[a-z_]|\Z)'
    func_match = re.search(func_pattern, content, re.DOTALL | re.IGNORECASE)
    
    if not func_match:
        return None
    
    func_body = func_match.group(2)
    
    topo = OrderedDict()
    routers = set()
    switches = OrderedDict()
    switch_to_routers = {}  # Track which routers connect to which switches
    
    # Extract routers
    # Pattern 1: Direct router names: add_router("r1")
    for match in re.finditer(r'add_router\s*\(\s*["\']([a-zA-Z0-9_-]+)["\']\s*\)', func_body):
        router_name = match.group(1)
        routers.add(router_name)
    
    # Pattern 2: Router loop: for routern in range(1, 5):
    range_match = re.search(r'for\s+\w+\s+in\s+range\s*\(\s*(\d+)\s*,\s*(\d+)\s*\):', func_body)
    if range_match:
        start = int(range_match.group(1))
        end = int(range_match.group(2))
        # Look for format strings in the next few lines
        next_lines = func_body[range_match.end():range_match.end()+200]
        if 'add_router' in next_lines and 'format' in next_lines:
            for i in range(start, end):
                routers.add(f"r{i}")

    # Pattern 3: Router loop over list: for router in ["rt1", "rt2"]:
    list_match = re.search(r'for\s+\w+\s+in\s+\[(.*?)\]:', func_body)
    if list_match:
        list_content = list_match.group(1)
        # Extract strings from the list
        items = re.findall(r'["\']([a-zA-Z0-9_-]+)["\']', list_content)
        # Verify add_router is called in the loop
        next_lines = func_body[list_match.end():list_match.end()+200]
        if 'add_router' in next_lines:
            for item in items:
                routers.add(item)
    
    # Extract switches and their connections
    # Pattern: switch = tgen.add_switch("s1") followed by switch.add_link(tgen.gears["r1"])
    switch_blocks = list(re.finditer(
        r'(?:switch|sw)\s*=\s*\w+\.add_switch\s*\(\s*["\']([a-zA-Z0-9_-]+)["\']\s*\)',
        func_body
    ))
    
    for i, match in enumerate(switch_blocks):
        sw_name = match.group(1)
        switches[sw_name] = True
        switch_to_routers[sw_name] = []
        
        # Find the block of code for this switch (until next switch or end)
        start_pos = match.end()
        if i + 1 < len(switch_blocks):
            end_pos = switch_blocks[i + 1].start()
        else:
            end_pos = len(func_body)
        
        switch_block = func_body[start_pos:end_pos]
        
        # Find add_link calls
        for link_match in re.finditer(r'add_link\s*\(\s*\w+\.gears\s*\[\s*["\']([a-zA-Z0-9_-]+)["\']\s*\]', switch_block):
            router_name = link_match.group(1)
            if router_name not in switch_to_routers[sw_name]:
                switch_to_routers[sw_name].append(router_name)
            # Also add this router if not already in routers set
            routers.add(router_name)
    
    # Build final simplified structure
    # router_name -> [switch_name1, switch_name2]
    result = OrderedDict()
    
    # Initialize all routers
    for rname in sorted(routers):
        result[rname] = []
        
        # Find connected switches
        for sw_name in switches:
            connected_routers = switch_to_routers.get(sw_name, [])
            if rname in connected_routers:
                result[rname].append(sw_name)
        
        # Sort switches
        result[rname].sort()
    
    return result


def find_test_files(topotests_dir):
    """Find all test directories with test_*.py files."""
    test_dirs = []
    
    for entry in os.listdir(topotests_dir):
        full_path = os.path.join(topotests_dir, entry)
        
        if not os.path.isdir(full_path):
            continue
        
        # Skip special directories
        if entry in ['lib', 'munet', 'docker', '__pycache__', '.git', '.pytest_cache']:
            continue
        
        # Check for test files
        try:
            files = os.listdir(full_path)
            test_files = [f for f in files if f.startswith('test_') and f.endswith('.py')]
            
            if test_files:
                test_dirs.append((entry, full_path, test_files))
        except:
            continue
    
    return sorted(test_dirs)


def main():
    parser = argparse.ArgumentParser(description='Batch export topologies to JSON')
    parser.add_argument('--limit', type=int, help='Limit number of tests to process')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--output-dir', help='Output directory for JSON files (default: each test dir)')
    parser.add_argument('--test-dirs', help='Comma-separated list of test directories to process')
    
    args = parser.parse_args()
    
    # Get topotests directory
    topotests_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Find all test directories
    test_dirs = find_test_files(topotests_dir)
    
    # Filter by specific tests if requested
    if args.test_dirs:
        requested = [d.strip() for d in args.test_dirs.split(',')]
        test_dirs = [d for d in test_dirs if d[0] in requested]
    
    if args.limit:
        test_dirs = test_dirs[:args.limit]
    
    print(f"Found {len(test_dirs)} test directories")
    print("=" * 70)
    
    results = {
        'success': [],
        'failed': [],
        'empty': []
    }
    
    for i, (test_name, test_path, test_files) in enumerate(test_dirs, 1):
        # Try each test file in the directory
        topo_data = None
        source_file = None
        
        for test_file in test_files:
            test_filepath = os.path.join(test_path, test_file)
            topo_data = extract_topology_from_file(test_filepath)
            
            if topo_data and (topo_data.get('routers') or topo_data.get('switches')):
                source_file = test_file
                break
        
            if topo_data:
                # Save JSON
                if args.output_dir:
                    output_file = os.path.join(args.output_dir, f"{test_name}.json")
                else:
                    output_file = os.path.join(test_path, 'exported_topology.json')
                
                try:
                    with open(output_file, 'w') as f:
                        json.dump(topo_data, f, indent=2)
                    
                    routers = len(topo_data)
                    switches = sum(len(s) for s in topo_data.values())
                    
                    status = f"✓ R:{routers} S_Links:{switches}"
                    if args.verbose:
                        status += f" ({source_file})"
                    
                    print(f"[{i:3d}/{len(test_dirs)}] {test_name:40s} {status}")
                    
                    results['success'].append({
                        'name': test_name,
                        'routers': routers,
                        'output': output_file
                    })
                except Exception as e:
                    print(f"[{i:3d}/{len(test_dirs)}] {test_name:40s} ✗ Write error: {e}")
                    results['failed'].append({'name': test_name, 'error': str(e)})
            
            else:
                if args.verbose:
                    print(f"[{i:3d}/{len(test_dirs)}] {test_name:40s} ✗ Parse failed")
                results['failed'].append({'name': test_name, 'error': 'Parse failed'})
    
    print("=" * 70)
    print(f"\nSummary:")
    print(f"  Successful:   {len(results['success']):4d}")
    print(f"  Empty:        {len(results['empty']):4d}")
    print(f"  Failed:       {len(results['failed']):4d}")
    print(f"  Total:        {len(test_dirs):4d}")
    
    # Save summary
    summary_file = os.path.join(topotests_dir, 'export_summary.json')
    with open(summary_file, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nSummary saved to: {summary_file}")
    
    if results['success']:
        print(f"\n✓ Successfully exported {len(results['success'])} topologies")
    
    return 0 if results['success'] else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
