import sys
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString # Import this

yaml_content = sys.stdin.read()

yaml = YAML()
yaml.preserve_quotes = True 
# yaml.indent(mapping=2, sequence=4, offset=2) # Default indentation should be fine

try:
    data = yaml.load(yaml_content)
except Exception as e:
    print(f"Error loading YAML: {e}", file=sys.stderr)
    sys.exit(1)

# Update namespace
if 'namespace' in data:
    data['namespace'] = 'huntarr'
else:
    print("Warning: top-level 'namespace' field not found.", file=sys.stderr)

# Update patches
if 'patches' in data and isinstance(data['patches'], list):
    for patch_item_idx, patch_item in enumerate(data['patches']): # Use enumerate for index if needed for debug
        if isinstance(patch_item, dict) and 'target' in patch_item and isinstance(patch_item['target'], dict):
            target = patch_item['target']
            patch_ops_str = patch_item.get('patch')
            
            if isinstance(patch_ops_str, str):
                patch_yaml_loader = YAML() # Use a fresh loader for the embedded YAML string
                try:
                    # The patch_ops_str is a multi-line string representing a list of operations
                    patch_operations = patch_yaml_loader.load(patch_ops_str) 
                    
                    made_change_in_patch = False
                    if isinstance(patch_operations, list): # Ensure it's a list of ops
                        for op in patch_operations:
                            if isinstance(op, dict) and op.get('op') == 'replace' and \
                               op.get('path') == '/metadata/name' and op.get('value') == 'smb-sonarr':
                                
                                # Check kind to apply correct new value
                                if target.get('kind') == 'PersistentVolume' or target.get('kind') == 'PersistentVolumeClaim':
                                    op['value'] = 'smb-huntarr'
                                    made_change_in_patch = True
                                    print(f"  Updated patch for {target.get('kind')}, target name {target.get('name')}: value set to smb-huntarr", file=sys.stderr)
                                    break # Assuming only one such op per patch item
                    
                    if made_change_in_patch:
                        # Dump the modified patch_operations list back to a string
                        from io import StringIO
                        temp_stream = StringIO()
                        # Use a simple dumper for the patch string, or configure as needed
                        # To ensure literal style for the block, construct LiteralScalarString
                        patch_yaml_dumper = YAML()
                        patch_yaml_dumper.dump(patch_operations, temp_stream)
                        new_patch_yaml_str = temp_stream.getvalue() # .strip() might remove necessary trailing newlines for block style
                        
                        # Ensure it's a literal block scalar string to maintain `|-`
                        patch_item['patch'] = LiteralScalarString(new_patch_yaml_str)

                except Exception as e_patch:
                     print(f"  Error processing patch string for target {target}: {e_patch}", file=sys.stderr)
            else:
                print(f"  Warning: Patch content for target {target} is not a string.", file=sys.stderr)
else:
    print("Warning: 'patches' field not found or not a list.", file=sys.stderr)


# Dump the full modified YAML to stdout
from io import StringIO
string_stream = StringIO()
yaml.dump(data, string_stream)
modified_yaml_content = string_stream.getvalue()
print(modified_yaml_content)
