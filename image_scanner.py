import yaml
import json
import glob
import sys

def parse_image_string(image_str, file_path_for_debug=""):
    if not isinstance(image_str, str):
        eprint(f"DEBUG: Non-string image value found in {file_path_for_debug}: {image_str}")
        return None, None
    
    name = image_str
    tag = 'latest' # Default if no tag is specified

    if '@' in image_str: # Handle digests, remove them for name part
        name_part, digest_part = image_str.split('@', 1)
        name = name_part # Keep the original name before @ for further parsing

    if ':' in name:
        parts = name.rsplit(':', 1)
        # Check if the part after ':' is a valid tag (not a port number like :8080)
        # A simple heuristic: if it contains a letter or typical version chars like '.', '-', it's likely a tag.
        # If it's all digits, it could be a port. This is not foolproof.
        # For this script, we'll assume if ':' is present, the last part is the tag.
        if len(parts) == 2:
            name = parts[0]
            tag = parts[1]
            
    # eprint(f"DEBUG: Parsed image string '{image_str}' to name='{name}', tag='{tag}' in {file_path_for_debug}")
    return name, tag

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

def find_images_recursive(data, file_path, images_found, path_trace=""):
    if isinstance(data, dict):
        # Pattern: image: { repository: "repo", tag: "tag" }
        if 'image' in data and isinstance(data['image'], dict):
            img_obj = data['image']
            repo = img_obj.get('repository')
            tag = img_obj.get('tag')
            if repo and tag is not None:
                registry = img_obj.get('registry')
                name = f"{registry}/{repo}" if registry and repo else repo
                images_found.add((file_path, name, str(tag)))
                eprint(f"DEBUG: {file_path} -> Added (Pat: image_dict): {name}:{str(tag)} from path {path_trace}.image")

        # Pattern: image: "repository:tag"
        elif 'image' in data and isinstance(data['image'], str):
            name, tag = parse_image_string(data['image'], file_path)
            if name:
                images_found.add((file_path, name, str(tag)))
                eprint(f"DEBUG: {file_path} -> Added (Pat: image_str): {name}:{str(tag)} from path {path_trace}.image")

        # Pattern: 'repository' and 'tag' keys at the same level
        elif 'repository' in data and 'tag' in data and isinstance(data['repository'], str) and data.get('tag') is not None:
            if not ('image' in data and isinstance(data['image'], dict)): # Avoid double count if part of image: {}
                 repo = data['repository']
                 tag_val = data['tag']
                 registry = data.get('registry')
                 name = f"{registry}/{repo}" if registry and repo else repo
                 images_found.add((file_path, name, str(tag_val)))
                 eprint(f"DEBUG: {file_path} -> Added (Pat: repo_tag_direct): {name}:{str(tag_val)} from path {path_trace}")
        
        # Pattern: Kustomize 'images' block
        # apiVersion: kustomize.config.k8s.io/v1beta1, kind: Kustomization
        if 'images' in data and isinstance(data['images'], list) and \
           'apiVersion' in data and 'kustomize.config.k8s.io' in data['apiVersion'] and \
           'kind' in data and data['kind'] == 'Kustomization':
            eprint(f"DEBUG: {file_path} -> Found Kustomize 'images' block at path {path_trace}.images")
            for i, img_override in enumerate(data['images']):
                if isinstance(img_override, dict):
                    orig_name = img_override.get('name') # Original name, for context
                    new_name_val = img_override.get('newName')
                    new_tag_val = img_override.get('newTag')

                    if new_name_val: # newName is mandatory for an effective override for this entry
                        final_name, final_tag = parse_image_string(new_name_val, file_path)
                        if new_tag_val: # if newTag is also specified, it overrides any tag in newName
                            final_tag = str(new_tag_val)
                        
                        if final_name: # final_name must be valid
                            images_found.add((file_path, final_name, final_tag))
                            eprint(f"DEBUG: {file_path} -> Added (Pat: kustomize_images): {final_name}:{final_tag} from {path_trace}.images[{i}] (orig: {orig_name})")
                    elif orig_name and new_tag_val: # Case: only tag is changed for an image
                        # This means we are only changing the tag of 'orig_name'.
                        # 'orig_name' itself isn't a deployed image if the chart uses different defaults.
                        # For this script, we only care about fully specified deployable images.
                        # If a kustomization only provides a newTag, it assumes the original image name is resolved elsewhere.
                        # We will record this as orig_name:new_tag_val as this is the effective image spec from this file.
                        images_found.add((file_path, orig_name, str(new_tag_val)))
                        eprint(f"DEBUG: {file_path} -> Added (Pat: kustomize_images_tag_only): {orig_name}:{str(new_tag_val)} from {path_trace}.images[{i}]")


        # Kubernetes container specs (simplified)
        for container_key_type in ['containers', 'initContainers']:
            if container_key_type in data and isinstance(data[container_key_type], list):
                for i, container in enumerate(data[container_key_type]):
                    if isinstance(container, dict) and 'image' in container and isinstance(container['image'], str):
                        name, tag = parse_image_string(container['image'], file_path)
                        if name:
                            images_found.add((file_path, name, str(tag)))
                            eprint(f"DEBUG: {file_path} -> Added (Pat: k8s_container_direct): {name}:{str(tag)} from path {path_trace}.{container_key_type}[{i}]")
        
        # General recursion
        for key, value in data.items():
            if key == 'image' and (isinstance(value, str) or ('repository' in value and 'tag' in value if isinstance(value, dict) else False)):
                continue
            if key == 'images' and 'apiVersion' in data and 'kustomize.config.k8s.io' in data['apiVersion']: # Avoid re-processing kustomize images list
                continue

            new_trace = f"{path_trace}.{key}" if path_trace else key
            find_images_recursive(value, file_path, images_found, new_trace)

    elif isinstance(data, list):
        for i, item in enumerate(data):
            new_trace = f"{path_trace}[{i}]"
            find_images_recursive(item, file_path, images_found, new_trace)

def main():
    base_path = 'apps/'
    yaml_files = glob.glob(f"{base_path}**/*.yaml", recursive=True)
    yml_files = glob.glob(f"{base_path}**/*.yml", recursive=True)
    filepaths = yaml_files + yml_files
    
    eprint(f"DEBUG: Found {len(filepaths)} YAML files to scan.")

    all_images_set = set()

    for fp in filepaths:
        eprint(f"DEBUG: Scanning file: {fp}")
        try:
            with open(fp, 'r', encoding='utf-8') as f:
                for doc_index, doc in enumerate(yaml.safe_load_all(f)):
                    if doc:
                        eprint(f"DEBUG: Processing document #{doc_index} in {fp}")
                        find_images_recursive(doc, fp, all_images_set, f"doc[{doc_index}]")
                    else:
                        eprint(f"DEBUG: Skipping empty document #{doc_index} in {fp}")
        except yaml.YAMLError as e:
            eprint(f"WARN: YAML parsing error in {fp}: {e}")
        except Exception as e:
            eprint(f"WARN: Unexpected error processing file {fp}: {e}")

    output_list = [
        {'file_path': item[0], 'image_name': item[1], 'image_tag': str(item[2])}
        for item in sorted(list(all_images_set))
    ]
    print(json.dumps(output_list, indent=2))

if __name__ == "__main__":
    main()
