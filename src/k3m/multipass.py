from dataclasses import dataclass
from typing import List
from .utils import process

@dataclass
class MultiPassNode:
    name: str
    state: str
    ip: str

def launch_node(name: str, cpus: int = 1, memory: str = "2G", disk: str = "10G", message: str = None, on_success: str = None) -> None:
    """Launch a new multipass node"""
    process(
        f"multipass launch -c {cpus} -m {memory} -d {disk} -n {name}",
        message=message or f"Launching node {name}",
        on_success=on_success or f"Node {name} launched"
    )

def get_node_ip(name: str, message: str = None) -> str:
    """Get the IP address of a multipass node"""
    return process(
        f"multipass info {name} | grep IPv4 | awk '{{print $2}}'",
        message=message or f"Getting IP address for {name}"
    ).strip()

def exec_command(node_name: str, command: str, message: str = None, on_success: str = None) -> str:
    """Execute a command on a multipass node"""
    return process(
        f"multipass exec {node_name} -- {command}",
        message=message,
        on_success=on_success
    )

def delete_nodes(node_names: List[str], message: str = None, on_success: str = None) -> None:
    """Delete multipass nodes"""
    if not node_names:
        return
    
    nodes_str = " ".join(node_names)
    process(
        f"multipass delete {nodes_str}",
        message=message or f"Deleting nodes",
        on_success=on_success or f"Deleted {len(node_names)} nodes"
    )

def purge_deleted_instances(message: str = None, on_success: str = None) -> None:
    """Purge deleted multipass instances"""
    process(
        "multipass purge",
        message=message or "Purging deleted instances",
        on_success=on_success or "Deleted instances purged"
    )

def start_nodes(node_names: List[str], message: str = None, on_success: str = None) -> None:
    """Start multipass nodes"""
    if not node_names:
        return
    
    nodes_str = " ".join(node_names)
    process(
        f"multipass start {nodes_str}",
        message=message or f"Starting nodes",
        on_success=on_success or f"Started {len(node_names)} nodes"
    )

def stop_nodes(node_names: List[str], message: str = None, on_success: str = None) -> None:
    """Stop multipass nodes"""
    if not node_names:
        return
    
    nodes_str = " ".join(node_names)
    process(
        f"multipass stop {nodes_str}",
        message=message or f"Stopping nodes",
        on_success=on_success or f"Stopped {len(node_names)} nodes"
    )

def install_k3s(node_name: str, args: str = "", is_server: bool = True, server_url: str = None, token: str = None, cluster_init: bool = False, message: str = None, on_success: str = None) -> None:
    """Install K3s on a node"""
    cmd_parts = ["bash -c 'curl -sfL https://get.k3s.io |"]
    
    if token and server_url:
        cmd_parts.append(f"K3S_TOKEN={token} K3S_URL=https://{server_url}:6443")
    
    if args:
        cmd_parts.append(f"INSTALL_K3S_EXEC=\"{args}\"")
    
    cmd_parts.append("sh -s -")
    
    if is_server:
        cmd_parts.append("server")
        if cluster_init:
            cmd_parts.append("--cluster-init")
    else:
        cmd_parts.append("agent")
    
    cmd_parts.append("'")
    
    exec_command(
        node_name,
        " ".join(cmd_parts),
        message=message or f"Installing K3s on {node_name}",
        on_success=on_success or f"K3s installed on {node_name}"
    )

def get_node_token(node_name: str, message: str = None) -> str:
    """Get the K3s node token from a server node"""
    return exec_command(
        node_name,
        "sudo cat /var/lib/rancher/k3s/server/node-token",
        message=message or "Getting node token"
    ).strip()

def get_kubeconfig(node_name: str, message: str = None) -> str:
    """Get the kubeconfig from a server node"""
    return exec_command(
        node_name,
        "sudo cat /etc/rancher/k3s/k3s.yaml",
        message=message or "Reading kubeconfig"
    )

def kubectl_drain_node(server_node: str, node_to_drain: str, message: str = None, on_success: str = None) -> None:
    """Drain a node using kubectl from a server node"""
    exec_command(
        server_node,
        f"sudo kubectl drain {node_to_drain} --ignore-daemonsets --delete-emptydir-data --force",
        message=message or f"Draining node {node_to_drain}",
        on_success=on_success or f"Node {node_to_drain} drained"
    )

def kubectl_delete_node(server_node: str, node_to_delete: str, message: str = None, on_success: str = None) -> None:
    """Delete a node using kubectl from a server node"""
    exec_command(
        server_node,
        f"sudo kubectl delete node {node_to_delete}",
        message=message or f"Removing node {node_to_delete} from Kubernetes",
        on_success=on_success or f"Node {node_to_delete} removed from Kubernetes"
    )

def stop_k3s_service(node_name: str, message: str = None) -> None:
    """Stop the K3s service on a node"""
    exec_command(
        node_name,
        "sudo systemctl stop k3s",
        message=message or "Stopping K3s service"
    )

# Multipass information retrieval
def multipass_list(message: str = None) -> str:
    """Get the raw output of multipass list command"""
    return process("multipass list", message=message or "Listing multipass instances").strip()

def get_multipass_nodes(message: str = None) -> List[MultiPassNode]:
    """Parse multipass list output into MultiPassNode objects"""
    output = multipass_list(message)
    
    if not output or output.strip() == "":
        return []
    
    nodes = []
    for line in output.split('\n'):
        if not line or line.startswith('Name'):
            continue  # Skip header line or empty lines
            
        parts = line.split()
        if len(parts) >= 3:
            name, state, ip = parts[0], parts[1], parts[2]
            nodes.append(MultiPassNode(name, state, ip))
    
    return nodes
