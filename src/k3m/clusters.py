from typing import Optional
from k3m.models import Cluster, NodeType, Node

def get_cluster_kubeconfig(cluster: Cluster) -> Optional[str]:
    """Get the kubeconfig file path for a cluster"""
    import os
    from rich.console import Console
    from .multipass import get_kubeconfig
    
    console = Console()
    
    try:
        first_server = Node.select().where(
            (Node.cluster == cluster) & 
            (Node.type == NodeType.SERVER.value)
        ).get()
    except Node.DoesNotExist:
        console.print(f"[red]Error:[/red] No server node found for cluster '{cluster.name}'")
        return None
    
    kubeconfig_content = get_kubeconfig(first_server.name)
    
    config_path = os.path.join(cluster.config_dir(), f"{cluster.name}.yaml")
    
    if not first_server.ip:
        console.print(f"[red]Error:[/red] No IP address found for server node in cluster '{cluster.name}'")
        return None
    
    with open(config_path, "w") as f:
        f.write(kubeconfig_content.replace("127.0.0.1", first_server.ip))
    
    return config_path