#!/usr/bin/env python3
"""
Migration script to import legacy JSON state into SQLite database.
This script detects and imports clusters from the old state.json format
into the new SQLite database format used with Peewee ORM.
"""

import json
import os
import sys
import datetime
from typing import Dict, Any

from k3m.models import Cluster, Node, NodeType, initialize_db


def load_json_state() -> Dict[str, Any]:
    """Load the legacy JSON state file if it exists."""
    config_dir = os.path.expanduser('~/.config/k3m')
    state_path = os.path.join(config_dir, "state.json")
    
    if not os.path.exists(state_path):
        print(f"No legacy state file found at {state_path}")
        return {}
    
    try:
        with open(state_path, "r") as f:
            return json.load(f)
    except json.JSONDecodeError:
        print(f"Error: {state_path} contains invalid JSON")
        return {}
    except Exception as e:
        print(f"Error reading {state_path}: {e}")
        return {}


def migrate_to_db() -> None:
    """Migrate data from JSON state file to SQLite database."""
    # Initialize database
    initialize_db()
    
    # Load legacy state
    legacy_state = load_json_state()
    if not legacy_state:
        print("No legacy state to migrate.")
        return
    
    print(f"Found {len(legacy_state)} clusters in legacy state file")
    
    # Track migration results
    migrated_clusters = 0
    migrated_nodes = 0
    
    # Migrate each cluster
    for cluster_name, cluster_data in legacy_state.items():
        # Skip if cluster already exists in database
        if Cluster.select().where(Cluster.name == cluster_name).exists():
            print(f"Cluster '{cluster_name}' already exists in database, skipping")
            continue
        
        try:
            # Parse created_at date if available
            created_at = datetime.datetime.now()
            if "created_at" in cluster_data:
                try:
                    created_at = datetime.datetime.strptime(
                        cluster_data["created_at"], "%Y-%m-%d %H:%M:%S"
                    )
                except ValueError:
                    print(f"Warning: Invalid date format for {cluster_name}, using current time")
            
            # Create cluster record
            cluster = Cluster.create(
                name=cluster_name,
                config_path=cluster_data.get("config_path", ""),
                created_at=created_at
            )
            migrated_clusters += 1
            
            # Create node records
            nodes_data = cluster_data.get("nodes", {})
            
            # Add server nodes
            for server_name in nodes_data.get("servers", []):
                Node.create(
                    cluster=cluster,
                    name=server_name,
                    type=NodeType.SERVER.value,
                    state="unknown"  # We'll sync actual state later
                )
                migrated_nodes += 1
            
            # Add agent nodes
            for agent_name in nodes_data.get("agents", []):
                Node.create(
                    cluster=cluster,
                    name=agent_name,
                    type=NodeType.AGENT.value,
                    state="unknown"  # We'll sync actual state later
                )
                migrated_nodes += 1
                
            print(f"Migrated cluster '{cluster_name}' with {len(nodes_data.get('servers', []))} servers and {len(nodes_data.get('agents', []))} agents")
            
        except Exception as e:
            print(f"Error migrating cluster '{cluster_name}': {e}")
    
    print(f"Migration complete: {migrated_clusters} clusters and {migrated_nodes} nodes migrated")
    config_dir = os.path.expanduser('~/.config/k3m')
    state_path = os.path.join(config_dir, "state.json")
    backup_path = os.path.join(config_dir, "state.json.bak")
    
    try:
        # Create backup
        os.rename(state_path, backup_path)
        print(f"Backed up legacy state file to {backup_path}")
    except Exception as e:
        print(f"Warning: Failed to backup legacy state file: {e}")


if __name__ == "__main__":
    try:
        migrate_to_db()
        print("Migration completed successfully")
        print("\nYou can now use the new SQLite database with your k3m commands.")
        print("The old state.json file has been backed up with .bak extension.")
    except Exception as e:
        print(f"Migration failed: {e}")
        sys.exit(1)

def detect_legacy():
    config_dir = os.path.expanduser('~/.config/k3m')
    state_path = os.path.join(config_dir, "state.json")
    return os.path.exists(state_path)


def migrate_legacy_state():
    if detect_legacy():
        try:
            migrate_to_db()
            print("Migration completed successfully")
            print("\nYou can now use the new SQLite database with your k3m commands.")
            print("The old state.json file has been backed up with .bak extension.")
        except Exception as e:
            print(f"Migration failed: {e}")    
