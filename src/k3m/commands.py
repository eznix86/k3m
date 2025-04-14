import os
from typing import Optional
from rich.console import Console
from rich.table import Table

from .models import Cluster, Node, NodeType
from .utils import ensure_multipass
from .clusters import get_cluster_kubeconfig
from .multipass import delete_nodes, purge_deleted_instances, start_nodes, stop_nodes, stop_k3s_service, install_k3s, get_multipass_nodes

console = Console()

def validate_cluster_params(name: str, servers: int, agents: int) -> bool:
    """Validate cluster creation parameters
    
    Args:
        name: Name of the cluster
        servers: Number of server nodes
        agents: Number of agent nodes
        
    Returns:
        bool: True if parameters are valid, False otherwise
    """
    if not name or not name.replace('-', '').isalnum():
        console.print(f"[red]Error:[/red] Invalid cluster name '{name}'. Use only letters, numbers, and hyphens.")
        return False
    
    if servers < 1:
        console.print("[red]Error:[/red] At least one server node is required")
        return False
    
    if agents < 0:
        console.print("[red]Error:[/red] Number of agents cannot be negative")
        return False

    if Cluster.select().where(Cluster.name == name).exists():
        console.print(f"[red]Error:[/red] Cluster '{name}' already exists")
        return False
        
    return True


def create_cluster_nodes(cluster, name: str, servers: int, agents: int):
    """Create the nodes for a cluster
    
    Args:
        cluster: The cluster object
        name: Name of the cluster
        servers: Number of server nodes
        agents: Number of agent nodes
        
    Returns:
        tuple: Lists of server and agent nodes
    """
    server_nodes = []
    agent_nodes = []
    
    try:
        for i in range(1, servers + 1):
            server_name = f"{name}-server-{i}"
            node = Node.create_node(
                server_name, 
                cluster, 
                NodeType.SERVER, 
                f"Launching server node {i}/{servers}", 
                f"Server node {i}/{servers} launched"
            )
            server_nodes.append(node)

        for i in range(1, agents + 1):
            agent_name = f"{name}-agent-{i}"
            node = Node.create_node(
                agent_name, 
                cluster, 
                NodeType.AGENT, 
                f"Launching agent node {i}/{agents}", 
                f"Agent node {i}/{agents} launched"
            )
            agent_nodes.append(node)
            
        return server_nodes, agent_nodes
    except Exception as e:
        # Clean up any created nodes on failure
        for node in server_nodes + agent_nodes:
            try:
                from .multipass import delete_nodes
                delete_nodes([node.name], message=f"Cleaning up node {node.name} after failure")
                node.delete_instance()
            except Exception:
                pass  # Best effort cleanup
        raise RuntimeError(f"Failed to create cluster nodes: {str(e)}") from e


def setup_cluster_nodes(server_nodes, agent_nodes, servers: int, agents: int, install_args: str = ""):
    """Set up the nodes in a cluster
    
    Args:
        server_nodes: List of server nodes
        agent_nodes: List of agent nodes
        servers: Number of server nodes
        agents: Number of agent nodes
        install_args: Additional arguments for k3s installation
    """
    try:
        # Setup server nodes
        if servers == 1:
            server_nodes[0].setup_single_node(install_args)
        else:
            server_nodes[0].setup_cluster_init(install_args)
            for i in range(1, servers):
                server_nodes[i].join_as_server(server_nodes[0], i+1, servers)
        
        # Setup agent nodes
        if agents > 0:
            for i in range(0, agents):
                agent_nodes[i].join_as_agent(server_nodes[0], i+1, agents)
    except Exception as e:
        raise RuntimeError(f"Failed to set up cluster nodes: {str(e)}") from e


def create_cluster(name: str, servers: int = 1, agents: int = 0, install_args: str = "") -> None:
    """Create a new cluster with the specified configuration
    
    Args:
        name: Name of the cluster
        servers: Number of server nodes (default: 1)
        agents: Number of agent nodes (default: 0)
        install_args: Additional arguments for k3s installation
    """
    try:
        ensure_multipass()
        
        if not validate_cluster_params(name, servers, agents):
            return

        console.print(f"Creating cluster [blue]{name}[/blue] with {servers} server(s) and {agents} agent(s)...")
        
        cluster = Cluster.create(
            name=name,
            config_path=os.path.join(Cluster.config_dir(), f"{name}.yaml")
        )
        
        try:
            server_nodes, agent_nodes = create_cluster_nodes(cluster, name, servers, agents)
            setup_cluster_nodes(server_nodes, agent_nodes, servers, agents, install_args)
            
            kubeconfig = get_cluster_kubeconfig(cluster)

            console.print("\n[green]✅ Cluster creation complete![/green]")
            if agents > 0:
                console.print(f"Added [blue]{agents}[/blue] agent node(s) to the cluster")
            console.print(f"\nTo use your cluster, run: [yellow]export KUBECONFIG={kubeconfig}[/yellow]")
            console.print("Then you can run kubectl commands, for example: [yellow]kubectl get nodes[/yellow]")
        except Exception as e:
            # Clean up the cluster on failure
            try:
                cluster.delete_instance(recursive=True)
            except Exception:
                pass  # Best effort cleanup
            console.print(f"[red]Error:[/red] {str(e)}")
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to create cluster: {str(e)}")


def sync_node_states():
    """Sync node states with multipass
    
    Returns:
        bool: True if sync was successful, False otherwise
    """
    try:
        from .multipass import get_multipass_nodes
        multipass_nodes = get_multipass_nodes("Fetching cluster information")
        Node.sync_with_multipass(multipass_nodes)
        return True
    except Exception as e:
        console.print(f"[yellow]Warning:[/yellow] Could not fetch multipass states: {e}")
        console.print("[yellow]Note:[/yellow] Showing last known states from database")
        return False


def calculate_cluster_state(cluster):
    """Calculate the overall state of a cluster based on its nodes
    
    Args:
        cluster: The cluster object
        
    Returns:
        tuple: (state, color)
    """
    # Calculate cluster state based on node states
    node_states = [node.state or 'Unknown' for node in cluster.nodes]
    
    if not node_states:
        return 'Unknown', 'white'
        
    if all(s == 'Running' for s in node_states):
        return 'Running', 'green'
    elif all(s == 'Stopped' for s in node_states):
        return 'Stopped', 'red'
    else:
        return 'Mixed', 'yellow'


def list_clusters() -> None:
    """List all clusters and their current states"""
    try:
        ensure_multipass()
        
        clusters = Cluster.select()
        if not clusters.exists():
            console.print("[yellow]No clusters found[/yellow]")
            return

        table = Table(
            "Name", "Servers", "Agents", "Status",
            show_header=True,
            box=False
        )

        sync_node_states()

        for cluster in clusters:
            cluster_state, status_color = calculate_cluster_state(cluster)
            
            table.add_row(
                cluster.name,
                str(len(cluster.servers)),
                str(len(cluster.agents)),
                f"[{status_color}]{cluster_state}[/{status_color}]"
            )

        console.print(table)
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to list clusters: {str(e)}")

def delete_multipass_nodes(nodes, cluster_name: str):
    """Delete multipass nodes for a cluster
    
    Args:
        nodes: List of node names
        cluster_name: Name of the cluster
    """
    if not nodes:
        return
        
    try:
        delete_nodes(
            nodes,
            message=f"Deleting cluster nodes for '{cluster_name}'",
            on_success=f"Deleted {len(nodes)} nodes"
        )
        purge_deleted_instances()
    except Exception as e:
        console.print(f"[yellow]Warning:[/yellow] Some nodes may not exist in multipass: {e}")


def delete_cluster(name: str) -> None:
    """Delete a cluster and clean up its state"""
    try:
        ensure_multipass()
        
        try:
            cluster = Cluster.get(Cluster.name == name)
        except Cluster.DoesNotExist:
            console.print(f"[yellow]Warning:[/yellow] Cluster '{name}' not found in database")
            return

        nodes = [node.name for node in cluster.nodes]
        delete_multipass_nodes(nodes, name)
        
        try:
            cluster.delete_instance(recursive=True)
            console.print(f"[green]✓[/green] Cluster '{name}' deleted from database")
        except Exception as e:
            console.print(f"[red]Error:[/red] Failed to delete cluster from database: {e}")
            raise
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to delete cluster: {e}")


def delete_all_clusters() -> None:
    """Delete all clusters and their nodes"""
    try:
        ensure_multipass()
        
        clusters = Cluster.select()
        if not clusters.exists():
            console.print("[yellow]No clusters found to delete[/yellow]")
            return
        
        cluster_count = clusters.count()
        console.print(f"Deleting all {cluster_count} clusters and their nodes...")
        
        all_nodes = []
        for cluster in clusters:
            all_nodes.extend([node.name for node in cluster.nodes])
        
        if all_nodes:
            delete_multipass_nodes(all_nodes, "all clusters")
        
        deleted_count = 0
        for cluster in clusters:
            try:
                cluster.delete_instance(recursive=True)
                deleted_count += 1
            except Exception as e:
                console.print(f"[yellow]Warning:[/yellow] Failed to delete cluster '{cluster.name}' from database: {e}")
        
        console.print(f"[green]✓[/green] Deleted {deleted_count} of {cluster_count} clusters from database")
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to delete all clusters: {e}")

def get_cluster_by_name(name: str):
    """Get a cluster by name
    
    Args:
        name: Name of the cluster
        
    Returns:
        Cluster or None: The cluster object if found, None otherwise
    """
    try:
        return Cluster.get(Cluster.name == name)
    except Cluster.DoesNotExist:
        console.print(f"[red]Error:[/red] Cluster '{name}' not found")
        return None


def start_cluster_nodes(cluster):
    """Start all nodes in a cluster
    
    Args:
        cluster: The cluster object
        
    Returns:
        bool: True if successful, False otherwise
    """
    nodes = [node.name for node in cluster.nodes]
    if not nodes:
        console.print("[yellow]Warning:[/yellow] No nodes found for this cluster")
        return False

    try:
        start_nodes(
            nodes,
            message=f"Starting cluster '{cluster.name}'",
            on_success=f"Cluster '{cluster.name}' started"
        )
        return True
    except Exception as e:
        console.print(f"[yellow]Warning:[/yellow] Some nodes may not exist in multipass: {e}")
        console.print("[yellow]Note:[/yellow] Will update database states for existing nodes")
        return False


def start_cluster(name: str) -> None:
    """Start a cluster"""
    try:
        ensure_multipass()
        
        cluster = get_cluster_by_name(name)
        if not cluster:
            return

        start_cluster_nodes(cluster)
        
        Node.update(state='Running').where(Node.cluster == cluster).execute()
        
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to start cluster: {str(e)}")

def stop_cluster_nodes(cluster):
    """Stop all nodes in a cluster
    
    Args:
        cluster: The cluster object
        
    Returns:
        bool: True if successful, False otherwise
    """
    nodes = [node.name for node in cluster.nodes]
    if not nodes:
        console.print("[yellow]Warning:[/yellow] No nodes found for this cluster")
        return False

    try:
        stop_nodes(
            nodes,
            message=f"Stopping cluster '{cluster.name}'",
            on_success=f"Cluster '{cluster.name}' stopped"
        )
        return True
    except Exception as e:
        console.print(f"[yellow]Warning:[/yellow] Some nodes may not exist in multipass: {e}")
        console.print("[yellow]Note:[/yellow] Will update database states for existing nodes")
        return False


def stop_cluster(name: str) -> None:
    """Stop a cluster"""
    try:
        ensure_multipass()
        
        cluster = get_cluster_by_name(name)
        if not cluster:
            return

        stop_cluster_nodes(cluster)
        
        Node.update(state='Stopped').where(Node.cluster == cluster).execute()
        
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to stop cluster: {str(e)}")

def validate_scale_params(cluster, servers: int, agents: int):
    """Validate cluster scaling parameters
    
    Args:
        cluster: The cluster object
        servers: Target number of server nodes
        agents: Target number of agent nodes
        
    Returns:
        tuple: (is_valid, current_servers, current_agents, target_servers, target_agents)
    """
    current_servers = len(cluster.servers)
    current_agents = len(cluster.agents)
    
    if servers is None and agents is None:
        console.print(f"Cluster '{cluster.name}' currently has {current_servers} server(s) and {current_agents} agent(s)")
        return False, current_servers, current_agents, None, None
    
    target_servers = servers if servers is not None else current_servers
    target_agents = agents if agents is not None else current_agents
    
    if target_servers < 1:
        console.print("[red]Error:[/red] At least one server node is required")
        return False, current_servers, current_agents, None, None
    
    if target_agents < 0:
        console.print("[red]Error:[/red] Number of agents cannot be negative")
        return False, current_servers, current_agents, None, None
    
    if target_servers < current_servers:
        console.print("[red]Error:[/red] Scaling down server nodes is not supported for safety reasons")
        console.print("[yellow]Note:[/yellow] Removing server nodes in an etcd-based cluster requires careful handling")
        console.print("[yellow]Note:[/yellow] Please delete and recreate the cluster if you need fewer server nodes")
        return False, current_servers, current_agents, None, None
    
    return True, current_servers, current_agents, target_servers, target_agents


def handle_single_to_multi_conversion(cluster, current_servers: int, target_servers: int):
    """Handle conversion from single-node to multi-node cluster
    
    Args:
        cluster: The cluster object
        current_servers: Current number of server nodes
        target_servers: Target number of server nodes
    """
    # Special case: scaling from single node to multi-node cluster
    # K3s docs: when you have an existing cluster using the default embedded SQLite database,
    # can convert it to etcd by simply restarting your K3s server with the --cluster-init flag
    is_scaling_from_single_to_multi = current_servers == 1 and target_servers > 1
    
    if is_scaling_from_single_to_multi:
        console.print("[yellow]Warning:[/yellow] Scaling from single-node to multi-node cluster requires converting SQLite to etcd")
        console.print("This will restart the server node with --cluster-init flag")
        
        first_server = cluster.servers[0]
        
        try:
            stop_k3s_service(first_server.name)
            
            install_k3s(
                first_server.name,
                is_server=True,
                cluster_init=True,
                message="Restarting server with cluster-init flag",
                on_success="Server restarted with cluster-init flag"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to convert single-node to multi-node cluster: {str(e)}") from e


def add_server_nodes(cluster, current_servers: int, target_servers: int):
    """Add server nodes to a cluster
    
    Args:
        cluster: The cluster object
        current_servers: Current number of server nodes
        target_servers: Target number of server nodes
        
    Returns:
        list: List of added server nodes
    """
    server_nodes = []
    servers_to_add = max(0, target_servers - current_servers)
    
    if servers_to_add <= 0:
        return server_nodes
    
    console.print(f"Adding {servers_to_add} server node(s) to cluster '{cluster.name}'...")
    
    try:
        first_server = cluster.servers[0]
        
        added_count = 0
        next_server_num = get_next_available_node_number(cluster.name, "server", current_servers + 1)
        
        while added_count < servers_to_add:
            server_name = f"{cluster.name}-server-{next_server_num}"
            
            try:
                node = Node.create_node(
                    server_name, 
                    cluster, 
                    NodeType.SERVER, 
                    f"Launching server node {added_count + 1}/{servers_to_add}", 
                    f"Server node {added_count + 1}/{servers_to_add} launched"
                )
                
                server_nodes.append(node)
                node.join_as_server(first_server, added_count + 1, servers_to_add)
                
                added_count += 1
                next_server_num += 1
            except Exception as e:
                if "already exists" in str(e):
                    # Skip this number and try the next one
                    console.print(f"[yellow]Warning:[/yellow] Node {server_name} already exists, trying next available name")
                    next_server_num += 1
                else:
                    # Re-raise other exceptions
                    raise
        
        return server_nodes
    except Exception as e:
        # Clean up any created nodes on failure
        for node in server_nodes:
            try:
                node.drain_and_delete(first_server)
            except Exception:
                pass  # Best effort cleanup
        raise RuntimeError(f"Failed to add server nodes: {str(e)}") from e


def get_next_available_node_number(cluster_name: str, node_type: str, start_from: int = 1):
    """Find the next available node number that doesn't conflict with existing multipass instances
    
    Args:
        cluster_name: Name of the cluster
        node_type: Type of node ('agent' or 'server')
        start_from: Starting number to check from
        
    Returns:
        int: Next available node number
    """
    try:
        # Get all existing multipass nodes
        multipass_nodes = get_multipass_nodes()
        existing_names = [node.name for node in multipass_nodes]
        
        # Find the next available number
        i = start_from
        while f"{cluster_name}-{node_type}-{i}" in existing_names:
            i += 1
        
        return i
    except Exception:
        # If we can't get multipass nodes, just return the starting number
        return start_from


def add_agent_nodes(cluster, current_agents: int, target_agents: int):
    """Add agent nodes to a cluster
    
    Args:
        cluster: The cluster object
        current_agents: Current number of agent nodes
        target_agents: Target number of agent nodes
        
    Returns:
        list: List of added agent nodes
    """
    agent_nodes = []
    agents_to_add = max(0, target_agents - current_agents)
    
    if agents_to_add <= 0:
        return agent_nodes
    
    console.print(f"Adding {agents_to_add} agent node(s) to cluster '{cluster.name}'...")
    
    try:
        first_server = cluster.servers[0]
        
        # Keep track of how many agents we've added
        added_count = 0
        next_agent_num = get_next_available_node_number(cluster.name, "agent", current_agents + 1)
        
        while added_count < agents_to_add:
            agent_name = f"{cluster.name}-agent-{next_agent_num}"
            
            try:
                node = Node.create_node(
                    agent_name, 
                    cluster, 
                    NodeType.AGENT, 
                    f"Launching agent node {added_count + 1}/{agents_to_add}", 
                    f"Agent node {added_count + 1}/{agents_to_add} launched"
                )
                
                agent_nodes.append(node)
                node.join_as_agent(first_server, added_count + 1, agents_to_add)
                
                added_count += 1
                next_agent_num += 1
            except Exception as e:
                if "already exists" in str(e):
                    # Skip this number and try the next one
                    console.print(f"[yellow]Warning:[/yellow] Node {agent_name} already exists, trying next available name")
                    next_agent_num += 1
                else:
                    # Re-raise other exceptions
                    raise
        
        return agent_nodes
    except Exception as e:
        # Clean up any created nodes on failure
        for node in agent_nodes:
            try:
                node.drain_and_delete(first_server)
            except Exception:
                pass  # Best effort cleanup
        raise RuntimeError(f"Failed to add agent nodes: {str(e)}") from e


def remove_agent_nodes(cluster, current_agents: int, target_agents: int):
    """Remove agent nodes from a cluster
    
    Args:
        cluster: The cluster object
        current_agents: Current number of agent nodes
        target_agents: Target number of agent nodes
    """
    agents_to_remove = max(0, current_agents - target_agents)
    
    if agents_to_remove <= 0:
        return
    
    console.print(f"Removing {agents_to_remove} agent node(s) from cluster '{cluster.name}'...")
    
    try:
        agents_to_delete = sorted(
            [node for node in cluster.agents],
            key=lambda node: node.name,
            reverse=True
        )[:agents_to_remove]
        
        first_server = cluster.servers[0]
        for node in agents_to_delete:
            node.drain_and_delete(first_server)
            
        purge_deleted_instances()
    except Exception as e:
        raise RuntimeError(f"Failed to remove agent nodes: {str(e)}") from e


def scale_cluster(name: str, servers: int = None, agents: int = None) -> None:
    """Scale a cluster by adding or removing nodes
    
    Args:
        name: Name of the cluster
        servers: Target number of server nodes (if None, won't change)
        agents: Target number of agent nodes (if None, won't change)
    """
    try:
        ensure_multipass()
        
        try:
            cluster = Cluster.get(Cluster.name == name)
        except Cluster.DoesNotExist:
            console.print(f"[red]Error:[/red] Cluster '{name}' not found")
            return
        
        is_valid, current_servers, current_agents, target_servers, target_agents = validate_scale_params(
            cluster, servers, agents
        )
        
        if not is_valid:
            return
            
        try:
            # Handle conversion from single-node to multi-node cluster
            handle_single_to_multi_conversion(cluster, current_servers, target_servers)
            
            # Add server nodes
            add_server_nodes(cluster, current_servers, target_servers)
            
            # Add agent nodes
            add_agent_nodes(cluster, current_agents, target_agents)
            
            remove_agent_nodes(cluster, current_agents, target_agents)
            
            console.print(f"[green]✅ Cluster scaling complete![/green]")
            console.print(f"Cluster '{name}' now has {target_servers} server(s) and {target_agents} agent(s)")
        except Exception as e:
            console.print(f"[red]Error:[/red] {str(e)}")
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to scale cluster: {str(e)}")

def get_kubeconfig(cluster_name: str) -> Optional[str]:
    """Get kubeconfig for a cluster by name
    
    Args:
        cluster_name: Name of the cluster
        
    Returns:
        Optional[str]: Path to the kubeconfig file if successful, None otherwise
    """
    try:
        ensure_multipass()
        
        cluster = get_cluster_by_name(cluster_name)
        if not cluster:
            return None

        try:
            return get_cluster_kubeconfig(cluster)
        except Exception as e:
            console.print(f"[red]Error:[/red] Failed to get kubeconfig: {str(e)}")
            return None
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to get kubeconfig: {str(e)}")
        return None
