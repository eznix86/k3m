import os
from datetime import datetime
from enum import Enum

from peewee import *
from playhouse.signals import Model
from playhouse.migrate import SqliteMigrator

DB_PATH = os.path.expanduser('~/.config/k3m/k3m.db')
DB_DIR = os.path.dirname(DB_PATH)

db = SqliteDatabase(
    DB_PATH,
    pragmas={
        'journal_mode': 'wal',
        'foreign_keys': 1,
        'cache_size': -1024 * 32,
        'synchronous': 0
    }
)
migrator = SqliteMigrator(db)

class BaseModel(Model):
    class Meta:
        database = db

class NodeType(Enum):
    SERVER = 'server'
    AGENT = 'agent'

class Cluster(BaseModel):
    """Model representing a k3m cluster"""
    name = CharField(unique=True)
    config_path = CharField()
    created_at = DateTimeField(default=datetime.now)

    @property
    def servers(self):
        return [node for node in self.nodes if node.type == NodeType.SERVER.value]

    @property
    def agents(self):
        return [node for node in self.nodes if node.type == NodeType.AGENT.value]

    @classmethod
    def config_dir(cls) -> str:
        """Get the configuration directory"""
        config_dir = os.path.expanduser('~/.config/k3m')
        os.makedirs(config_dir, exist_ok=True)
        return config_dir

    def save(self, *args, **kwargs):
        if not self.config_path:
            self.config_path = os.path.join(self.config_dir(), f"{self.name}.yaml")
        return super().save(*args, **kwargs)

class Node(BaseModel):
    """Model representing a node in a cluster"""
    name = CharField()
    type = CharField()  # 'server' or 'agent'
    cluster = ForeignKeyField(Cluster, backref='nodes', on_delete='CASCADE')
    ip = CharField(null=True)
    state = CharField(null=True)  # Will be updated from multipass

    class Meta:
        indexes = (
            (('name', 'cluster'), True),
        )
    
    @property
    def is_server(self) -> bool:
        """Check if this node is a server node"""
        return self.type == NodeType.SERVER.value
    
    @property
    def is_agent(self) -> bool:
        """Check if this node is an agent node"""
        return self.type == NodeType.AGENT.value
    
    def update_ip(self) -> None:
        """Update the IP address of this node from multipass"""
        from .multipass import get_node_ip
        self.ip = get_node_ip(self.name)
        self.save()
    
    def get_token(self) -> str:
        """Get the K3s node token from this server node"""
        from .multipass import get_node_token
        if not self.is_server:
            raise ValueError("Cannot get token from non-server node")
        return get_node_token(self.name)
    
    def setup_single_node(self, install_args: str = "") -> None:
        """Set up this node as a single-node K3s cluster"""
        from .multipass import install_k3s
        if not self.is_server:
            raise ValueError("Cannot set up single-node cluster on non-server node")
        install_k3s(
            self.name, 
            args=install_args,
            message=f"Initializing single-node cluster on {self.name}",
            on_success="Single-node Kubernetes cluster initialized"
        )
    
    def setup_cluster_init(self, install_args: str = "") -> None:
        """Set up this node as the first node in a multi-node K3s cluster"""
        from .multipass import install_k3s
        if not self.is_server:
            raise ValueError("Cannot initialize cluster on non-server node")
        install_k3s(
            self.name, 
            args=install_args,
            cluster_init=True,
            message=f"Initializing control plane on {self.name}",
            on_success="Control plane initialized"
        )
    
    def join_as_server(self, master_node, position: int, total: int) -> None:
        """Join this node to the cluster as a server"""
        from .multipass import install_k3s
        if not self.is_server:
            raise ValueError("Cannot join as server with non-server node")
        install_k3s(
            self.name,
            is_server=True,
            server_url=master_node.ip,
            token=master_node.get_token(),
            message=f"Joining server node {position}/{total}",
            on_success=f"Server node {position}/{total} joined to cluster"
        )
    
    def join_as_agent(self, master_node, position: int, total: int) -> None:
        """Join this node to the cluster as an agent"""
        from .multipass import install_k3s
        if not self.is_agent:
            raise ValueError("Cannot join as agent with non-agent node")
        install_k3s(
            self.name,
            is_server=False,
            server_url=master_node.ip,
            token=master_node.get_token(),
            message=f"Joining agent node {position}/{total}",
            on_success=f"Agent node {position}/{total} joined to cluster"
        )
    
    def drain_and_delete(self, master_node) -> None:
        """Drain this node from Kubernetes and delete it"""
        from .multipass import kubectl_drain_node, kubectl_delete_node, delete_nodes
        try:
            kubectl_drain_node(master_node.name, self.name)
            kubectl_delete_node(master_node.name, self.name)
            delete_nodes([self.name])
            self.delete_instance()
        except Exception as e:
            from rich.console import Console
            console = Console()
            console.print(f"[yellow]Warning:[/yellow] Error removing node {self.name}: {e}")
    
    @classmethod
    def sync_with_multipass(cls, multipass_instances) -> None:
        """Sync nodes with multipass instances
        
        Args:
            multipass_instances: List of multipass instances with name and state attributes
        
        Note:
            This method only updates states for existing nodes. It does not delete nodes
            that are missing from multipass to avoid data loss in case multipass is
            temporarily unavailable.
        """
        if not multipass_instances:
            return
            
        instance_states = {instance.name: instance.state for instance in multipass_instances}
        
        for node in cls.select():
            if node.name in instance_states:
                node.state = instance_states[node.name]
                node.save()
    
    @classmethod
    def create_node(cls, name: str, cluster, node_type, message: str = None, on_success: str = None) -> 'Node':
        """Create a new node in multipass and the database"""
        from .multipass import launch_node
        
        launch_node(name, message=message, on_success=on_success)
        
        node = cls.create(
            name=name,
            type=node_type.value,
            cluster=cluster,
            state='Running'
        )
        
        node.update_ip()
        
        return node

def initialize_db():
    """Initialize the database and create tables"""
    os.makedirs(DB_DIR, exist_ok=True)
    
    try:
        db.connect()
        db.create_tables([Cluster, Node])
    except Exception as e:
        print(f"Database initialization error: {e}")
        raise
    finally:
        if not db.is_closed():
            db.close()