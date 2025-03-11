import subprocess
import sys
from typing import Optional, NoReturn
from rich.console import Console
from halo import Halo

console = Console()

def abort_if(condition: bool, message: Optional[str] = None) -> None:
    """Abort the program if the condition is True"""
    if condition:
        if message:
            console.print(f"[red]Error:[/red] {message}")
        sys.exit(1)

def check_multipass_status() -> tuple[bool, str]:
    """Check multipass status and return (is_available, error_message)"""
    try:
        # Check if multipass is installed
        result = subprocess.run(['which', 'multipass'], capture_output=True, text=True)
        if result.returncode != 0:
            return False, "Multipass is not installed. Install it with: brew install multipass"

        multipass_path = result.stdout.strip()
        if not multipass_path:
            return False, "Multipass installation is corrupted. Try reinstalling: brew reinstall multipass"

        # Check if daemon is running
        version_result = subprocess.run([multipass_path, 'version'], capture_output=True, text=True)
        if version_result.returncode != 0:
            return False, "Multipass daemon is not running. Try: multipass version"

        # Check if we can list instances
        list_result = subprocess.run([multipass_path, 'list'], capture_output=True, text=True)
        if list_result.returncode != 0:
            if 'permission denied' in list_result.stderr.lower():
                return False, "Permission denied. Ensure you have the necessary permissions to use multipass."
            return False, f"Multipass is not working properly: {list_result.stderr}"

        return True, ""
    except Exception as e:
        return False, f"Unexpected error checking multipass: {str(e)}"

def ensure_multipass() -> None:
    """Ensure multipass is available and properly configured"""
    is_available, error_message = check_multipass_status()
    if not is_available:
        console.print(f"[red]Error:[/red] {error_message}")
        console.print("\nFor more help, visit: https://multipass.run/docs")
        sys.exit(1)

def process(cmd: str, message: Optional[str] = None, on_success: Optional[str] = None) -> str:
    """Run a shell command with Halo spinner for status indication"""
    spinner = Halo(text=message or "Processing...", spinner='dots')
    try:
        spinner.start()
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if result.returncode != 0:
            spinner.fail(f"Error: {result.stderr}")
            raise RuntimeError(f"Command failed: {cmd}")
        
        if on_success:
            spinner.succeed(on_success)
        else:
            spinner.stop()
        
        return result.stdout.strip()
    except Exception as e:
        spinner.fail(str(e))
        raise
    finally:
        if spinner.spinner_id:
            spinner.stop()