#!/usr/bin/env python3

import click
from rich.console import Console
from .commands import (
    create_cluster,
    list_clusters,
    delete_cluster,
    delete_all_clusters,
    start_cluster,
    stop_cluster,
    scale_cluster,
    get_kubeconfig,
)
from .models import initialize_db
from .migrate_json_to_db import migrate_legacy_state

initialize_db()
migrate_legacy_state()

console = Console()


@click.group()
def cli():
    """k3m - Lightweight k3s cluster manager"""
    return 0


@cli.group()
def cluster():
    """Cluster management commands"""
    pass


@cluster.command()
@click.argument("name")
@click.option("--servers", "-s", default=1, help="Number of server nodes (default: 1)")
@click.option("--agents", "-a", default=0, help="Number of agent nodes (default: 0)")
@click.option("--install-args", "-i", default="", help="alias for INSTALL_K3S_EXEC")
def create(name, servers, agents, install_args):
    """Create a new cluster"""
    create_cluster(name, servers, agents, install_args)


@cluster.command()
def list():
    """List all clusters"""
    list_clusters()


@cluster.command()
@click.argument("name", required=False)
@click.option("--force", "-f", is_flag=True, help="Force deletion without confirmation")
@click.option("--all", "-a", is_flag=True, help="Delete all clusters")
def delete(name, force, all):
    """Delete a cluster"""
    if all:
        if not force:
            if not click.confirm("Are you sure you want to delete ALL clusters?"):
                return
        delete_all_clusters()
    elif name:
        if not force:
            if not click.confirm(f"Are you sure you want to delete cluster {name}?"):
                return
        delete_cluster(name)
    else:
        console.print("[red]Error:[/red] Either provide a cluster name or use --all to delete all clusters")
        console.print("Run 'k3m cluster delete --help' for usage information")


@cluster.command()
@click.argument("name")
def start(name):
    """Start a cluster"""
    start_cluster(name)


@cluster.command()
@click.argument("name")
def stop(name):
    """Stop a cluster"""
    stop_cluster(name)


@cluster.command()
@click.argument("name")
@click.option("--servers", "-s", type=int, help="Target number of server nodes")
@click.option("--agents", "-a", type=int, help="Target number of agent nodes")
def scale(name, servers, agents):
    """Scale a cluster by adding or removing nodes"""
    scale_cluster(name, servers, agents)


@cli.group()
def kubeconfig():
    """Kubeconfig management commands"""
    pass


@kubeconfig.command()
@click.argument("name")
def write(name):
    """Write kubeconfig for a cluster"""
    config_file = get_kubeconfig(name)
    if config_file:
        console.print(config_file)


if __name__ == "__main__":
    cli()
