"""Build a call tree from function data.

Each function row lists its callees.
"""

from pyopsy.collect.functions import callee_id, function_key


def build_tree(rows):
    """Return an icicle tree and a graph from function data.

    A recursive call is one edge from a function to itself.
    """
    nodes = []
    edges = []
    by_id = {}
    incoming = {}
    for row in rows:
        node_id = callee_id(
            function_key(row["filename"], row["firstlineno"], row["name"])
        )
        node = {
            "id": node_id,
            "name": row["name"],
            "filename": row["filename"],
            "firstlineno": row["firstlineno"],
            "ncalls": row["ncalls"],
            "tottime": row["tottime"],
            "cumtime": row["cumtime"],
            "mem": row.get("mem") or 0,
            "mem_own": row.get("mem_own") or 0,
            "mem_mean": row.get("mem_mean") or 0,
            "mem_peak": row.get("mem_peak") or 0,
        }
        nodes.append(node)
        by_id[node_id] = node
        incoming.setdefault(node_id, 0)
        for callee_key, callee in row.get("callees", {}).items():
            if isinstance(callee_key, tuple):
                callee_node = callee_id(callee_key)
            else:
                callee_node = callee_key
            edges.append(
                {
                    "caller": node_id,
                    "callee": callee_node,
                    "ncalls": callee["ncalls"],
                    "tottime": callee["tottime"],
                    "cumtime": callee["cumtime"],
                    "mem": callee.get("mem") or 0,
                    "mem_own": callee.get("mem_own") or 0,
                    "mem_mean": callee.get("mem_mean") or 0,
                    "mem_peak": callee.get("mem_peak") or 0,
                }
            )
            incoming[callee_node] = incoming.get(callee_node, 0) + 1
    roots = [node["id"] for node in nodes if incoming.get(node["id"], 0) == 0]
    if not roots and nodes:
        roots = [max(nodes, key=lambda item: item["cumtime"])["id"]]
    children = {}
    for edge in edges:
        children.setdefault(edge["caller"], []).append(edge)
    seen = set()

    def icicle(node_id, depth):
        node = by_id.get(node_id)
        if node is None or depth > 24:
            return None
        recursive = node_id in seen
        child_nodes = []
        if not recursive:
            seen.add(node_id)
            for edge in children.get(node_id, []):
                child = icicle(edge["callee"], depth + 1)
                if child is not None:
                    child_nodes.append(child)
        return {
            "id": node_id,
            "name": node["name"],
            "time": node["cumtime"],
            "mem": node.get("mem") or 0,
            "ncalls": node["ncalls"],
            "children": child_nodes,
        }

    forest = []
    for root in roots:
        item = icicle(root, 0)
        if item is not None:
            forest.append(item)
    return {"nodes": nodes, "edges": edges, "icicle": forest}
