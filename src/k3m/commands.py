from sys import stdout
from typing import Optional, List
from rich.console import Console
from rich.table import Table
from .models import Cluster, ClusterNodes
from .utils import process, ensure_multipass

console = Console()

def create_cluster(name: str, servers: int = 1, agents: int = 0) -> None:
    """Create a new cluster"""
    ensure_multipass()
    
    if Cluster.get(name):
        console.print(f"[red]Error:[/red] Cluster '{name}' already exists")
        return

    console.print(f"Creating cluster [blue]{name}[/blue] with {servers} server(s) and {agents} agent(s)...")

    server_nodes = []
    try:
        for i in range(1, servers + 1):
            server_name = f"{name}-server-{i}"
            server_nodes.append(server_name)
            process(
                f"multipass launch -c 1 -m 2G -d 10G -n {server_name}",
                message=f"Launching server node {i}/{servers}",
                on_success=f"Server node {i}/{servers} launched"
            )

        # Get the first server's IP
        server_ip = process(
            f"multipass info {server_nodes[0]} | grep IPv4 | awk '{{print $2}}'",
            message="Getting server IP address"
        )

        # Initialize Kubernetes
        if servers == 1:
            process(
                f"multipass exec {server_nodes[0]} -- bash -c 'curl -sfL https://get.k3s.io | sh -'",
                message="Initializing single-node cluster",
                on_success="Single-node Kubernetes cluster initialized"
            )
            node_token = process(
                f"multipass exec {server_nodes[0]} -- sudo cat /var/lib/rancher/k3s/server/node-token",
                message="Getting node token"
            )
        else:
            process(
                f"multipass exec {server_nodes[0]} -- bash -c 'curl -sfL https://get.k3s.io | sh -s - server --cluster-init'",
                message="Initializing control plane",
                on_success="Control plane initialized"
            )
            node_token = process(
                f"multipass exec {server_nodes[0]} -- sudo cat /var/lib/rancher/k3s/server/node-token",
                message="Getting node token"
            )

            for i, server in enumerate(server_nodes[1:], 2):
                process(
                    f"multipass exec {server} -- bash -c 'curl -sfL https://get.k3s.io | K3S_TOKEN={node_token} K3S_URL=https://{server_ip}:6443 sh -s - server'",
                    message=f"Joining server node {i}/{servers} to cluster",
                    on_success=f"Server node {i}/{servers} joined cluster"
                )

        agent_nodes = []
        for i in range(1, agents + 1):
            agent_name = f"{name}-agent-{i}"
            agent_nodes.append(agent_name)
            process(
                f"multipass launch -c 1 -m 1G -d 5G -n {agent_name}",
                message=f"Launching agent node {i}/{agents}",
                on_success=f"Agent node {i}/{agents} launched"
            )
            process(
                f"multipass exec {agent_name} -- bash -c 'curl -sfL https://get.k3s.io | K3S_TOKEN={node_token} K3S_URL=https://{server_ip}:6443 sh -'",
                message=f"Joining agent node {i}/{agents} to cluster",
                on_success=f"Agent node {i}/{agents} joined cluster"
            )

        # Create and save cluster state
        cluster = Cluster.create(
            name=name,
            nodes=ClusterNodes(servers=server_nodes, agents=agent_nodes)
        )

        # Get kubeconfig
        kubeconfig = get_kubeconfig(name)
        
        console.print("\n[green]✅ Cluster creation complete![/green]")
        if agents > 0:
            console.print(f"Added [blue]{agents}[/blue] agent node(s) to the cluster")
        console.print(f"\nTo use your cluster, run: [yellow]export KUBECONFIG={kubeconfig}[/yellow]")
        console.print("Then you can run kubectl commands, for example: [yellow]kubectl get nodes[/yellow]")

    except Exception as e:
        console.print(f"[red]Error creating cluster:[/red] {str(e)}")
        # Cleanup on failure
        cleanup_nodes = server_nodes + agent_nodes if 'agent_nodes' in locals() else server_nodes
        if cleanup_nodes:
            try:
                process(
                    f"multipass delete {' '.join(cleanup_nodes)}",
                    message="Cleaning up failed cluster nodes",
                    on_success="Cleaned up failed nodes"
                )
                process("multipass purge")
            except Exception as cleanup_error:
                console.print(f"[red]Error during cleanup:[/red] {str(cleanup_error)}")
        raise

def list_clusters() -> None:
    """List all clusters"""
    ensure_multipass()
    
    clusters = Cluster.get_all()
    if not clusters:
        console.print("[yellow]No clusters found[/yellow]")
        return

    table = Table(
        "Name", "Servers", "Agents", "Status",
        show_header=True,
        box=False
    )

    instance_states = {}
    try:
        output = process("multipass list", message="Fetching cluster information")
        lines = output.split('\n')
        if len(lines) > 1:
            for line in lines[1:]:
                parts = line.strip().split()
                if len(parts) >= 2:
                    name, state = parts[0], parts[1]
                    instance_states[name] = state
    except Exception as e:
        console.print(f"[red]Warning:[/red] Could not fetch instance states: {e}")

    for name, cluster in clusters.items():
        # Get states for all nodes in the cluster
        node_states = [instance_states.get(node, 'Unknown') 
                      for node in cluster.nodes.all_nodes()]
        
        cluster_state = 'Running' if all(s == 'Running' for s in node_states) else \
                       'Stopped' if all(s == 'Stopped' for s in node_states) else \
                       'Mixed' if node_states else 'Unknown'
        
        status_color = {
            'Running': 'green',
            'Stopped': 'red',
            'Mixed': 'yellow',
            'Unknown': 'white'
        }[cluster_state]

        table.add_row(
            name,
            str(len(cluster.nodes.servers)),
            str(len(cluster.nodes.agents)),
            f"[{status_color}]{cluster_state}[/{status_color}]",
        )

    console.print(table)

def delete_cluster(name: str) -> None:
    """Delete a cluster"""
    ensure_multipass()
    
    cluster = Cluster.get(name)
    if not cluster:
        console.print(f"[yellow]Warning:[/yellow] Cluster '{name}' not found in state")
        # Try to find and delete any matching nodes
        try:
            output = process("multipass list", message="Searching for cluster nodes")
            node_list = []
            for line in output.split('\n')[1:]:
                parts = line.strip().split()
                if parts and parts[0].startswith(f"{name}-"):
                    node_list.append(parts[0])
            
            if node_list:
                process(
                    f"multipass delete {' '.join(node_list)}",
                    message=f"Deleting found nodes for '{name}'",
                    on_success=f"Deleted {len(node_list)} nodes"
                )
                process("multipass purge", message="Purging deleted instances")
        except Exception as e:
            console.print(f"[red]Error:[/red] Failed to clean up nodes: {e}")
        return

    try:
        nodes = cluster.nodes.all_nodes()
        if nodes:
            process(
                f"multipass delete {' '.join(nodes)}",
                message=f"Deleting cluster nodes for '{name}'",
                on_success=f"Deleted {len(nodes)} nodes"
            )
            process("multipass purge", message="Purging deleted instances")
        
        # Remove cluster state
        cluster.delete()
        console.print(f"[green]✓[/green] Cluster '{name}' deleted")
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to delete cluster: {e}")

def start_cluster(name: str) -> None:
    """Start a cluster"""
    ensure_multipass()
    
    cluster = Cluster.get(name)
    if not cluster:
        console.print(f"[red]Error:[/red] Cluster '{name}' not found")
        return

    try:
        nodes = cluster.nodes.all_nodes()
        if not nodes:
            console.print("[yellow]Warning:[/yellow] No nodes found for this cluster")
            return

        process(
            f"multipass start {' '.join(nodes)}",
            message=f"Starting cluster '{name}'",
            on_success=f"Cluster '{name}' started"
        )
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to start cluster: {e}")

def stop_cluster(name: str) -> None:
    """Stop a cluster"""
    ensure_multipass()
    
    cluster = Cluster.get(name)
    if not cluster:
        console.print(f"[red]Error:[/red] Cluster '{name}' not found")
        return

    try:
        nodes = cluster.nodes.all_nodes()
        if not nodes:
            console.print("[yellow]Warning:[/yellow] No nodes found for this cluster")
            return

        process(
            f"multipass stop {' '.join(nodes)}",
            message=f"Stopping cluster '{name}'",
            on_success=f"Cluster '{name}' stopped"
        )
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to stop cluster: {e}")

def get_kubeconfig(name: str) -> Optional[str]:
    """Get kubeconfig for a cluster"""
    ensure_multipass()
    
    cluster = Cluster.get(name)
    if not cluster:
        console.print(f"[red]Error:[/red] Cluster '{name}' not found")
        return None

    try:
        first_server = cluster.nodes.servers[0]
        ip = process(
            f"multipass info {first_server} | grep IPv4 | awk '{{print $2}}'",
            message="Getting server IP address"
        )
        kubeconfig = process(
            f"multipass exec {first_server} -- sudo cat /etc/rancher/k3s/k3s.yaml",
            message="Reading kubeconfig"
        )

        config_path = cluster.get_kubeconfig_path()
        with open(config_path, "w") as f:
            f.write(kubeconfig.replace("127.0.0.1", ip))

        return config_path
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to get kubeconfig: {e}")
        return None