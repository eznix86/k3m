# k3m - Lightweight k3s Cluster Manager

A simple CLI tool to manage k3s clusters using canonical's multipass.

## Installation

### Ubuntu/Debian
```bash
sudo apt install pipx
pipx install k3m
```

### MacOS
```bash
brew install pipx
pipx install k3m
```

### Development Installation
```bash
# Clone the repository
git clone https://github.com/eznix86/k3m.git
cd k3m

# Install using poetry
poetry install
```

## Usage

```bash
# Create a cluster
k3m cluster create my-cluster --servers 1 --agents 2

# List clusters
k3m cluster list

# Delete a cluster
k3m cluster delete my-cluster

# Start/Stop a cluster
k3m cluster start my-cluster
k3m cluster stop my-cluster

# Get kubeconfig
k3m kubeconfig write my-cluster
# or
export KUBECONFIG=$(k3m kubeconfig write my-cluster)
```
