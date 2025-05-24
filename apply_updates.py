import json
import sys
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString, DoubleQuotedScalarString
from packaging.version import parse as parse_version, InvalidVersion

def eprint(*args, **kwargs):
    """Helper function to print to stderr."""
    print(*args, file=sys.stderr, **kwargs)

def parse_image_string(image_str):
    if not isinstance(image_str, str):
        return None, None
    
    name = image_str
    tag = None # Default if no tag is specified or if it's part of a digest

    if '@' in image_str: # Handle digests, image_name@sha256:digest
        name_part, digest_part = image_str.split('@', 1)
        # For this function, we are interested in name and potential tag before digest
        name = name_part 

    if ':' in name:
        parts = name.rsplit(':', 1)
        # Check if the part after ':' could be a tag
        # For apply_updates, we need to be more careful than in scanning.
        # Rely on currentVersion matching.
        name = parts[0]
        tag = parts[1]
            
    return name, tag

def update_yaml_data(data, target_image_name, current_version, new_version, file_path):
    """
    Recursively searches and updates image versions in YAML data.
    Returns True if an update was made, False otherwise.
    """
    if isinstance(data, dict):
        # Pattern 1: Direct image string: image: "name:tag" or image: "name" (implies latest or a digest)
        if 'image' in data and isinstance(data['image'], str):
            img_full_str = data['image']
            img_name_in_yaml, img_tag_in_yaml = parse_image_string(img_full_str)

            # Normalize target_image_name if it has library/ prefix from crane
            normalized_target_image_name = target_image_name
            if target_image_name.startswith("library/") and not img_name_in_yaml.startswith("library/"):
                 normalized_target_image_name = target_image_name.split("library/",1)[1]


            if img_name_in_yaml == normalized_target_image_name and str(img_tag_in_yaml) == str(current_version):
                new_image_str = f"{img_name_in_yaml}:{new_version}"
                # Preserve quote style if possible
                if isinstance(data['image'], DoubleQuotedScalarString):
                    data['image'] = DoubleQuotedScalarString(new_image_str)
                elif isinstance(data['image'], LiteralScalarString): # Less common for image strings
                    data['image'] = LiteralScalarString(new_image_str)
                else:
                    data['image'] = new_image_str
                eprint(f"  Updated direct image in {file_path}: {img_full_str} -> {new_image_str}")
                return True
            # Handle cases where current_version might be 'latest' implicitly if tag is missing
            elif img_name_in_yaml == normalized_target_image_name and img_tag_in_yaml is None and str(current_version).lower() == 'latest':
                new_image_str = f"{img_name_in_yaml}:{new_version}"
                if isinstance(data['image'], DoubleQuotedScalarString): data['image'] = DoubleQuotedScalarString(new_image_str)
                else: data['image'] = new_image_str
                eprint(f"  Updated direct image (implicit latest) in {file_path}: {img_full_str} -> {new_image_str}")
                return True


        # Pattern 2: Image object: image: { repository: "name", tag: "tag" }
        if 'image' in data and isinstance(data['image'], dict):
            img_obj = data['image']
            repo = img_obj.get('repository')
            tag = img_obj.get('tag')
            
            # Normalize target_image_name for repo comparison
            normalized_target_image_name_for_repo = target_image_name
            if target_image_name.startswith("library/") and repo and not repo.startswith("library/"):
                 normalized_target_image_name_for_repo = target_image_name.split("library/",1)[1]
            
            # Check if registry is part of repo or separate
            registry = img_obj.get('registry')
            full_repo_name_in_yaml = f"{registry}/{repo}" if registry and repo else repo

            if (repo == target_image_name or full_repo_name_in_yaml == target_image_name or \
                repo == normalized_target_image_name_for_repo or full_repo_name_in_yaml == normalized_target_image_name_for_repo) \
                and str(tag) == str(current_version):
                
                # Preserve quote style for tag
                if isinstance(img_obj['tag'], DoubleQuotedScalarString):
                    img_obj['tag'] = DoubleQuotedScalarString(str(new_version))
                elif isinstance(img_obj['tag'], LiteralScalarString): # Should not happen for tags typically
                     img_obj['tag'] = LiteralScalarString(str(new_version))
                else:
                    img_obj['tag'] = str(new_version) # Cast new_version to string as tags can be numbers
                eprint(f"  Updated image object tag in {file_path}: {repo}:{tag} -> {new_version}")
                return True
        
        # Pattern 3: Kustomize 'images' block
        if 'images' in data and isinstance(data['images'], list) and \
           data.get('kind') == 'Kustomization': # Check kind for safety
            for img_override in data['images']:
                if isinstance(img_override, dict):
                    kustomize_name = img_override.get('name')      # Original name referred in kustomize
                    kustomize_newName = img_override.get('newName') # Can be full image OR just name part
                    kustomize_newTag = img_override.get('newTag')

                    # Case 1: Update newTag if newName matches target_image_name (without tag) and newTag matches current_version
                    if kustomize_newName and kustomize_newTag and \
                       kustomize_newName == target_image_name and str(kustomize_newTag) == str(current_version):
                        img_override['newTag'] = str(new_version)
                        eprint(f"  Updated Kustomize newTag for {kustomize_newName} in {file_path}: {kustomize_newTag} -> {new_version}")
                        return True
                    
                    # Case 2: Update newTag if name matches target_image_name and newTag matches current_version (newName might be absent)
                    if not kustomize_newName and kustomize_name and kustomize_newTag and \
                       kustomize_name == target_image_name and str(kustomize_newTag) == str(current_version):
                        img_override['newTag'] = str(new_version)
                        eprint(f"  Updated Kustomize newTag for {kustomize_name} in {file_path}: {kustomize_newTag} -> {new_version}")
                        return True

                    # Case 3: newName contains the full image name and current_version as its tag
                    if kustomize_newName and not kustomize_newTag: # Tag is part of newName
                        parsed_newName_name, parsed_newName_tag = parse_image_string(kustomize_newName)
                        if parsed_newName_name == target_image_name and str(parsed_newName_tag) == str(current_version):
                            img_override['newName'] = f"{parsed_newName_name}:{new_version}"
                            eprint(f"  Updated Kustomize newName in {file_path}: {kustomize_newName} -> {img_override['newName']}")
                            return True
            # If an image is only defined by `name:` and its original chart tag,
            # and we want to update it, we'd add `newTag` or `newName`.
            # This script focuses on updating existing version strings.

        # Recurse
        for key, value in data.items():
            if update_yaml_data(value, target_image_name, current_version, new_version, file_path):
                return True

    elif isinstance(data, list):
        for item in data:
            if update_yaml_data(item, target_image_name, current_version, new_version, file_path):
                return True
                
    return False

def main():
    try:
        with open("image_updates_proposed.json", 'r') as f:
            proposed_updates = json.load(f)
    except FileNotFoundError:
        eprint("Error: image_updates_proposed.json not found.")
        return
    except json.JSONDecodeError:
        eprint("Error: Could not decode image_updates_proposed.json.")
        return

    yaml = YAML()
    yaml.preserve_quotes = True
    # yaml.indent(mapping=2, sequence=4, offset=2) # Optional: control indentation

    successful_changes = []
    error_logs = []

    for update_entry in proposed_updates:
        if not update_entry.get("updateNeeded", False):
            continue

        file_path = update_entry["filePath"]
        image_name = update_entry["imageName"] # Name from registry/previous scan
        current_version = str(update_entry["currentVersion"])
        new_version = str(update_entry["newVersion"])

        eprint(f"\nAttempting update for: {image_name}:{current_version} -> {new_version} in {file_path}")

        if new_version.startswith("Error:"):
            eprint(f"  Skipping due to error in newVersion: {new_version}")
            error_logs.append(f"Skipped {file_path} for {image_name} due to error in newVersion: {new_version}")
            continue
        
        try:
            with open(file_path, 'r') as f:
                # Use list to load all documents if multi-doc YAML
                yaml_docs = list(yaml.load_all(f))
            
            made_change_in_file = False
            for doc_idx, doc_data in enumerate(yaml_docs):
                if update_yaml_data(doc_data, image_name, current_version, new_version, file_path):
                    made_change_in_file = True
                    # No need to break here, one image might be in multiple docs (though unlikely for version updates)
                    # or multiple distinct images could be in one file but handled by outer loop over proposed_updates.
                    # This loop is for multi-document YAML files.
            
            if made_change_in_file:
                with open(file_path, 'w') as f:
                    yaml.dump_all(yaml_docs, f)
                log_message = f"Successfully updated {image_name} from {current_version} to {new_version} in {file_path}"
                eprint(f"  {log_message}")
                successful_changes.append(log_message)
            else:
                err_msg = f"Image {image_name}:{current_version} not found or not updated in {file_path} as expected."
                eprint(f"  Warning: {err_msg}")
                error_logs.append(err_msg)

        except FileNotFoundError:
            err_msg = f"File {file_path} not found for update."
            eprint(f"  Error: {err_msg}")
            error_logs.append(err_msg)
        except Exception as e:
            err_msg = f"Error processing file {file_path}: {e}"
            eprint(f"  Error: {err_msg}")
            error_logs.append(err_msg)

    eprint("\n--- Summary ---")
    eprint("Successful changes:")
    for log in successful_changes:
        eprint(f"- {log}")
    
    if error_logs:
        eprint("\nErrors and Warnings:")
        for log in error_logs:
            eprint(f"- {log}")

if __name__ == "__main__":
    main()
