import os
import pathspec
import pyperclip

# descriptions for known files
FILE_COMMENTS = {
    "auth_lib.py": "# Functions for eve authentication management",
    "sso.py": "# Functions for OAuth2 login, token refresh",
    "token_store.py": "# Functions for saving/loading tokens (encrypted)",
    "utils.py": "# misc supporting functions for auth",
    "station_market.py": "# Market data retrieval (public stations)",
    "private_structure_market.py": "# Private structure market data retrival using structures_found_through_structure_discovery.py",
    "structure_discovery.py": "# Private structure discovery for markets.",
    "wallet.py": "# Wallet data retrieval",
    "contracts.py": "# Contracts data retrieval",
    "industry.py": "# Industry jobs retrieval",
    "blueprints.py": "# Blueprints retrieval",
    "skills.py": "# Skills retrieval",
    "models.py": "# SQLAlchemy models (or raw SQL schema definitions)",
    "database.py": "# DB connection setup, e.g., SQLite connection",
    "config.yaml": "# Configuration (e.g., list of region/structure IDs, polling intervals)",
    "main.py": "# Main entry point to start the scheduler",
    "scheduler.py": "# Orchestration of periodic tasks",
}

def load_gitignore(base_path):
    ignore_path = os.path.join(base_path, ".gitignore")
    patterns = []

    if os.path.exists(ignore_path):
        with open(ignore_path, "r") as f:
            patterns = f.read().splitlines()

    # Always ignore .git, __pycache__, etc.
    patterns += [".git", "__pycache__/", "*.pyc", ".DS_Store"]
    return pathspec.PathSpec.from_lines("gitwildmatch", patterns)

def is_ignored(path, base_path, spec):
    rel_path = os.path.relpath(path, base_path)
    return spec.match_file(rel_path)

def build_tree(root, prefix="", base_path="", spec=None, lines=None):
    if lines is None:
        lines = []

    entries = sorted(os.listdir(root))
    entries_full = [os.path.join(root, e) for e in entries]

    files = [e for e in entries_full if os.path.isfile(e) and not is_ignored(e, base_path, spec)]
    dirs = [e for e in entries_full if os.path.isdir(e) and not is_ignored(e, base_path, spec)]

    for i, d in enumerate(dirs):
        is_last = (i == len(dirs) - 1 and not files)
        connector = "└── " if is_last else "├── "
        lines.append(prefix + connector + os.path.basename(d) + "/")
        sub_prefix = "    " if is_last else "│   "
        build_tree(d, prefix + sub_prefix, base_path, spec, lines)

    for i, f in enumerate(files):
        is_last = (i == len(files) - 1)
        connector = "└── " if is_last else "├── "
        fname = os.path.basename(f)
        comment = False #FILE_COMMENTS.get(fname, "")
        line = prefix + connector + fname
        '''
        if comment:
            line += " " + comment
            '''
        lines.append(line)

    return lines

if __name__ == "__main__":
    base = os.path.dirname(os.path.abspath(__file__))
    spec = load_gitignore(base)

    # Build the tree
    header = f"{os.path.basename(base)}/"
    lines = [header]
    lines += build_tree(base, prefix="", base_path=base, spec=spec)

    tree_str = "  \n".join(lines)

    # Copy to clipboard
    pyperclip.copy(tree_str)
    print("Directory tree copied to clipboard!")
