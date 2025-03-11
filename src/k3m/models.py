import os
import json
from datetime import datetime
from typing import List, Dict, Optional
from pydantic import BaseModel, Field, validator

class ClusterNodes(BaseModel):
    """Represents the nodes in a cluster"""
    servers: List[str] = Field(default_factory=list)
    agents: List[str] = Field(default_factory=list)

    def all_nodes(self) -> List[str]:
        """Get all nodes in the cluster"""
        return self.servers + self.agents

class Cluster(BaseModel):
    """Model representing a k3m cluster"""
    name: str
    nodes: ClusterNodes
    config_path: str
    created_at: str = Field(default_factory=lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    @validator('config_path')
    def validate_config_path(cls, v: str, values: Dict) -> str:
        """Ensure config path is in the correct directory"""
        if not v.startswith(cls.config_dir()):
            v = os.path.join(cls.config_dir(), f"{values['name']}.yaml")
        return v

    @classmethod
    def get(cls, name: str) -> Optional['Cluster']:
        """Get a cluster by name"""
        try:
            state_file = os.path.join(cls.config_dir(), 'state.json')
            if os.path.exists(state_file):
                with open(state_file, 'r') as f:
                    state = json.load(f)
                    if name in state:
                        data = state[name]
                        # Handle old format migration
                        if 'nodes' not in data:
                            data = {
                                'nodes': {
                                    'servers': data.get('servers', []),
                                    'agents': data.get('agents', [])
                                },
                                'config_path': data.get('config_path', ''),
                                'created_at': data.get('created_at', '')
                            }
                        return cls(name=name, **data)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: Error reading state file: {e}")
        return None

    @classmethod
    def get_all(cls) -> Dict[str, 'Cluster']:
        """Get all clusters"""
        try:
            state_file = os.path.join(cls.config_dir(), 'state.json')
            if os.path.exists(state_file):
                with open(state_file, 'r') as f:
                    state = json.load(f)
                    clusters = {}
                    for name, data in state.items():
                        # Handle old format migration
                        if 'nodes' not in data:
                            data = {
                                'nodes': {
                                    'servers': data.get('servers', []),
                                    'agents': data.get('agents', [])
                                },
                                'config_path': data.get('config_path', ''),
                                'created_at': data.get('created_at', '')
                            }
                        clusters[name] = cls(name=name, **data)
                    return clusters
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: Error reading state file: {e}")
        return {}

    @classmethod
    def create(cls, name: str, nodes: ClusterNodes) -> 'Cluster':
        """Create a new cluster"""
        cluster = cls(
            name=name,
            nodes=nodes,
            config_path=os.path.join(cls.config_dir(), f'{name}.yaml')
        )
        cluster.save()
        return cluster

    @classmethod
    def config_dir(cls) -> str:
        """Get the configuration directory"""
        config_dir = os.path.expanduser('~/.config/k3m')
        os.makedirs(config_dir, exist_ok=True)
        return config_dir

    def save(self) -> None:
        """Save the cluster state"""
        try:
            state_file = os.path.join(self.config_dir(), 'state.json')
            clusters = self.get_all()
            clusters[self.name] = self
            with open(state_file, 'w') as f:
                json.dump({name: cluster.dict(exclude={'name'}) 
                        for name, cluster in clusters.items()}, f, indent=2)
        except OSError as e:
            print(f"Warning: Error saving state file: {e}")

    def delete(self) -> None:
        """Delete the cluster"""
        try:
            state_file = os.path.join(self.config_dir(), 'state.json')
            clusters = self.get_all()
            if self.name in clusters:
                del clusters[self.name]
                with open(state_file, 'w') as f:
                    json.dump({name: cluster.dict(exclude={'name'}) 
                            for name, cluster in clusters.items()}, f, indent=2)
                if os.path.exists(self.config_path):
                    os.remove(self.config_path)
        except OSError as e:
            print(f"Warning: Error deleting cluster state: {e}")

    def get_kubeconfig_path(self) -> str:
        """Get the path to the cluster's kubeconfig file"""
        return self.config_path