import sys
import os

# Get the absolute path to the project root
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)

# Ensure the current directory is also in the path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)
sys.path.insert(0, os.path.dirname(current_dir))

from app.services.host_service import create_session, get_session, update_session, delete_session

delete_session("default")
create_session("default", "host-uuid", "192.168.0.0")
update_session("default", {"is_locked": True, "world_id": "default"})
session = get_session("default")
print(session)
