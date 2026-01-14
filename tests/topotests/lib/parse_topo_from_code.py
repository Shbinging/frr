#!/usr/bin/env python3
# SPDX-License-Identifier: ISC
#
# parse_topo_from_code.py
# Parse topology structure from Python test files using AST
#

"""
Static code parser to extract topology information from Python test files.
This uses AST parsing to extract router and switch definitions without
actually executing the code.
"""

import ast
import json
import os
from collections import OrderedDict


def parse_build_topo_function(filepath):
    """
    Parse a Python file and extract topology information from build_topo function.
    
    Args:
        filepath: Path to Python test file
    
    Returns:
        Dictionary with topology structure or None if parsing fails
    """
    try:
        with open(filepath, 'r') as f:
            source = f.read()
        
        tree = ast.parse(source)
        
        # Find the build_topo function
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and 'build' in node.name.lower() and 'topo' in node.name.lower():
                return extract_topology_from_function(node)
        
        return None
    except Exception as e:
        return None


def extract_topology_from_function(func_node):
    """
    Extract topology information from build_topo AST node.
    
    Args:
        func_node: AST FunctionDef node
        
    Returns:
        Dictionary with routers, switches, and links
    """
    topo = OrderedDict()
    routers = set()
    switches = OrderedDict()
    links = []  # List of (switch, router) tuples
    
    # Walk through function body
    for stmt in ast.walk(func_node):
        # Look for add_router calls
        if isinstance(stmt, ast.Call):
            if hasattr(stmt.func, 'attr'):
                if stmt.func.attr == 'add_router':
                    # Extract router name
                    if stmt.args and isinstance(stmt.args[0], ast.Constant):
                        routers.add(stmt.args[0].value)
                    elif stmt.args and isinstance(stmt.args[0], ast.JoinedStr):
                        # Format string like "r{}".format(routern)
                        # We'll handle this by pattern matching
                        pass
                
                elif stmt.func.attr == 'add_switch':
                    # Extract switch name
                    if stmt.args and isinstance(stmt.args[0], ast.Constant):
                        sw_name = stmt.args[0].value
                        switches[sw_name] = {'links': []}
                
                elif stmt.func.attr == 'add_link':
                    # This is a switch.add_link call
                    # Try to extract the gear name
                    if stmt.args:
                        arg = stmt.args[0]
                        # Look for tgen.gears["r1"] pattern
                        if isinstance(arg, ast.Subscript):
                            if isinstance(arg.slice, ast.Constant):
                                gear_name = arg.slice.value
                                # Need to find which switch this belongs to
                                # This is complex, we'll handle it in  post-processing
                                links.append(gear_name)
    
    # Handle simple patterns like range(1, 5) for routers
    for stmt in func_node.body:
        if isinstance(stmt, ast.For):
            # Check if it's creating routers in a loop
            if isinstance(stmt.iter, ast.Call) and hasattr(stmt.iter.func, 'id') and stmt.iter.func.id == 'range':
                # Get range parameters
                if len(stmt.iter.args) == 2:
                    start = stmt.iter.args[0].value if isinstance(stmt.iter.args[0], ast.Constant) else 1
                    end = stmt.iter.args[1].value if isinstance(stmt.iter.args[1], ast.Constant) else 0
                    
                    # Look for add_router in loop body
                    for inner_stmt in ast.walk(stmt):
                        if isinstance(inner_stmt, ast.Call) and hasattr(inner_stmt.func, 'attr'):
                            if inner_stmt.func.attr == 'add_router':
                                # Add routers r1, r2, ... based on range
                                for i in range(start, end):
                                    routers.add(f"r{i}")
    
    topo['routers'] = sorted(list(routers))
    topo['switches'] = switches if switches else {}
    
    return topo


def parse_topology_simple(filepath):
    """
    Simple regex-based parser for extracting topology information.
    This is a fallback when AST parsing is too complex.
    
    Args:
        filepath: Path to Python test file
        
    Returns:
        Dictionary with topology structure
    """
    import re
    
    topo = OrderedDict()
    routers = set()
    switches = OrderedDict()
    switch_links = {}  # switch_name -> [list of connected routers]
    
    try:
        with open(filepath, 'r') as f:
            content = f.read()
        
        # Find build_topo or similar function
        func_match = re.search(r'def\s+(build\w*topo\w*|.*build.*)\(.*?\):(.*?)(?=\ndef\s+|\Z)', content, re.DOTALL | re.IGNORECASE)
        if not func_match:
            return None
        
        func_body = func_match.group(2)
        
        # Find router creation patterns
        # Pattern 1: tgen.add_router("r1")
        for match in re.finditer(r'add_router\s*\(\s*["\']([^"\']+)["\']\s*\)', func_body):
            routers.add(match.group(1))
        
        # Pattern 2: tgen.add_router("r{}".format(routern)) in a range loop
        range_match = re.search(r'for\s+\w+\s+in\s+range\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)', func_body)
        if range_match:
            start, end = int(range_match.group(1)), int(range_match.group(2))
            for i in range(start, end):
                routers.add(f"r{i}")
        
        # Find switch creation
        for match in re.finditer(r'add_switch\s*\(\s*["\']([^"\']+)["\']\s*\)', func_body):
            sw_name = match.group(1)
            switches[sw_name] = {'type': 'switch', 'links': {}}
            switch_links[sw_name] = []
        
        # Find switch.add_link patterns
        # Look for: switch = tgen.add_switch("s1") followed by switch.add_link(tgen.gears["r1"])
        switch_blocks = re.finditer(
            r'switch\s*=\s*\w+\.add_switch\s*\(\s*["\']([^"\']+)["\']\s*\)(.*?)(?=switch\s*=|\ndef\s+|\Z)',
            func_body,
            re.DOTALL
        )
        
        for block_match in switch_blocks:
            sw_name = block_match.group(1)
            block = block_match.group(2)
            
            if sw_name not in switch_links:
                switch_links[sw_name] = []
            
            # Find all add_link calls in this block
            for link_match in re.finditer(r'add_link\s*\(\s*\w+\.gears\s*\[\s*["\']([^"\']+)["\']\s*\]\s*\)', block):
                router_name = link_match.group(1)
                switch_links[sw_name].append(router_name)
        
        # Build final structure
        topo['routers'] = OrderedDict()
        for rname in sorted(routers):
            topo['routers'][rname] = {
                'type': 'router',
                'links': {}
            }
        
        # Add switch link information
        topo['switches'] = OrderedDict()
        for sw_name in sorted(switches.keys()):
            connected_routers = switch_links.get(sw_name, [])
            topo['switches'][sw_name] = {
                'type': 'switch',
                'links': {r: {} for r in connected_routers}
            }
            
            # Also add reverse links to routers
            for r in connected_routers:
                if r in topo['routers']:
                    topo['routers'][r]['links'][sw_name] = {}
        
        # Add metadata
        topo['metadata'] = {
            'total_routers': len(topo['routers']),
            'total_switches': len(topo['switches']),
            'parsed_from': os.path.basename(filepath)
        }
        
        return topo
    
    except Exception as e:
        return None


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        result = parse_topology_simple(sys.argv[1])
        if result:
            print(json.dumps(result, indent=2))
        else:
            print("Failed to parse topology")
    else:
        print("Usage: python3 parse_topo_from_code.py <test_file.py>")
