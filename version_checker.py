import json
import json5 # For parsing renovate.json5
import re
import subprocess
from packaging.version import parse as parse_version, InvalidVersion
from packaging.specifiers import SpecifierSet, InvalidSpecifier
import os
import sys

# Set PATH to include .local/bin for crane if it was installed there by pip for the user
os.environ["PATH"] = os.path.expanduser("~/.local/bin") + os.pathsep + os.environ["PATH"]
CRANE_CMD = '/usr/local/bin/crane'


def eprint(*args, **kwargs):
    """Helper function to print to stderr."""
    print(*args, file=sys.stderr, **kwargs)


def get_tags_from_registry(image_name):
    eprint(f"Fetching tags for {image_name} using {CRANE_CMD}...")
    try:
        # Using stdout=PIPE and iterating lines
        process = subprocess.Popen([CRANE_CMD, 'ls', image_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate(timeout=60) # process.stdout is now a string

        if process.returncode != 0:
            eprint(f"Error fetching tags for {image_name} with {CRANE_CMD} (return code {process.returncode}): {stderr}")
            # Try Docker Hub default if applicable
            if '/' not in image_name:
                eprint(f"Retrying {image_name} as library/{image_name} for Docker Hub default...")
                process_retry = subprocess.Popen([CRANE_CMD, 'ls', f"library/{image_name}"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                stdout_retry, stderr_retry = process_retry.communicate(timeout=60)
                if process_retry.returncode == 0:
                    tags_retry = stdout_retry.strip().splitlines() # Use splitlines()
                    eprint(f"Found tags for library/{image_name} ({len(tags_retry)} total). First 15: {tags_retry[:15]}...")
                    return tags_retry, f"library/{image_name}"
                else:
                    eprint(f"Error fetching tags for library/{image_name} with {CRANE_CMD}: {stderr_retry}")
                    return None, f"library/{image_name}"
            return None, image_name # Original name if error and not Docker Hub default case

        tags = stdout.strip().splitlines() # Use splitlines()
        
        eprint(f"Found tags for {image_name} ({len(tags)} total). First 15: {tags[:15]}...")
        if image_name == "vault":
             eprint(f"  DEBUG FOR VAULT: Raw tag count: {len(tags)}")
             eprint(f"  DEBUG FOR VAULT: Last 15 tags from crane: {tags[-15:]}...")
             if "1.17.0" not in tags: eprint("  DEBUG FOR VAULT: Tag '1.17.0' NOT in raw tags list from crane!")
             if "1.16.3" not in tags: eprint("  DEBUG FOR VAULT: Tag '1.16.3' NOT in raw tags list from crane!")
             if "1.16.1" not in tags: eprint("  DEBUG FOR VAULT: Tag '1.16.1' NOT in raw tags list from crane!")
        return tags, image_name

    except subprocess.TimeoutExpired:
        eprint(f"Timeout fetching tags for {image_name}")
        if process and process.poll() is None: process.kill() # Ensure process is killed
        return None, image_name
    except FileNotFoundError:
        eprint(f"CRANE COMMAND '{CRANE_CMD}' NOT FOUND.")
        raise
    except Exception as e: # Catch any other unexpected errors during subprocess handling
        eprint(f"An unexpected error occurred with subprocess for {image_name}: {e}")
        return None, image_name


def parse_allowed_versions(allowed_str):
    if not allowed_str:
        return None
    match = re.fullmatch(r"(\d+)\.x", allowed_str)
    if match:
        major = int(match.group(1))
        return SpecifierSet(f">={major}.0.0,<{major + 1}.0.0")
    match = re.fullmatch(r"(\d+)\.(\d+)\.x", allowed_str)
    if match:
        major = int(match.group(1))
        minor = int(match.group(2))
        return SpecifierSet(f">={major}.{minor}.0,<{major}.{minor + 1}.0")
    try:
        return SpecifierSet(allowed_str)
    except InvalidSpecifier:
        eprint(f"Warning: Could not parse allowedVersions string '{allowed_str}' into a valid specifier.")
        return None

def get_latest_matching_version(tags, image_name_for_debug, specifier_set=None, current_version_str=""):
    if not tags:
        return None

    candidate_versions = []
    current_semver = None
    if current_version_str:
        try:
            parsed_tag = current_version_str[1:] if current_version_str.startswith('v') else current_version_str
            current_semver = parse_version(parsed_tag)
        except InvalidVersion:
             eprint(f"  Note: Current version '{current_version_str}' for {image_name_for_debug} is not standard semver.")

    for tag_idx, tag in enumerate(tags): 
        tag_to_parse = tag
        
        if image_name_for_debug == "vault" and tag in ["1.17.0", "1.16.3", "1.16.1", "1.13.3"]:
            eprint(f"  VAULT_TAG_TRACE: Encountered tag '{tag}' at index {tag_idx}.")

        if tag.lower() in ['latest', 'main', 'master', 'dev', 'stable', 'edge', 'rolling', 'nightly', 
                           'alpha', 'beta', 'rc', 'test', 'testing', 'snapshot', 'canary']:
            if image_name_for_debug == "vault" and tag in ["1.17.0", "1.16.3", "1.16.1", "1.13.3"]: 
                 eprint(f"  VAULT_TAG_TRACE: Tag '{tag}' was skipped by common name filter.")
            continue
        
        if tag.startswith('v'):
            tag_to_parse = tag[1:]
        
        try:
            version = parse_version(tag_to_parse)
            candidate_versions.append(version)
            if image_name_for_debug == "vault" and tag in ["1.17.0", "1.16.3", "1.16.1", "1.13.3"]:
                 eprint(f"  VAULT_TAG_TRACE: Tag '{tag}' parsed as {version} and added to candidates.")
        except InvalidVersion:
            if image_name_for_debug == "vault" and tag in ["1.17.0", "1.16.3", "1.16.1", "1.13.3"]:
                 eprint(f"  VAULT_TAG_TRACE: Tag '{tag}' failed to parse.")
            continue 

    if image_name_for_debug == "vault":
        eprint(f"  DEBUG FOR VAULT: All parsed candidate_versions ({len(candidate_versions)}): Sample: {sorted([v for v in candidate_versions if str(v).startswith('1.17') or str(v).startswith('1.16') or str(v).startswith('1.13')], reverse=True)[:30]}...")


    if not candidate_versions:
        eprint(f"  No parseable semantic versions found in tags for {image_name_for_debug}.")
        return None

    if specifier_set:
        filtered_versions = [v for v in candidate_versions if specifier_set.contains(v)]
        eprint(f"  For spec '{specifier_set}' on {image_name_for_debug}, filtered versions (sample): {sorted(filtered_versions, reverse=True)[:5]}")
    else:
        if current_semver and current_semver.is_prerelease:
            filtered_versions = [
                v for v in candidate_versions 
                if not v.is_prerelease or (v.is_prerelease and v.base_version >= current_semver.base_version)
            ]
        elif not current_semver and current_version_str: 
             filtered_versions = candidate_versions 
        else: 
            filtered_versions = [v for v in candidate_versions if not v.is_prerelease]
            if not filtered_versions and candidate_versions: 
                eprint(f"  No stable versions found for {image_name_for_debug}. Considering pre-releases as fallback.")
                is_any_stable = any(not v.is_prerelease for v in candidate_versions)
                if not is_any_stable:
                    filtered_versions = candidate_versions
    
    if image_name_for_debug == "vault":
        eprint(f"  DEBUG FOR VAULT: Final filtered_versions before max ({len(filtered_versions)}): Sample: {sorted([v for v in filtered_versions if str(v).startswith('1.17') or str(v).startswith('1.16') or str(v).startswith('1.13')], reverse=True)[:30]}...")
        if filtered_versions:
            eprint(f"  DEBUG FOR VAULT: Type of elements in filtered_versions: {type(filtered_versions[0])}")
            test_v117 = parse_version("1.17.0")
            is_117_present = test_v117 in filtered_versions
            eprint(f"  DEBUG FOR VAULT: Is Version('1.17.0') in filtered_versions? {is_117_present}")
            if not is_117_present: 
                for cv in candidate_versions:
                    if cv.base_version == "1.17.0" and not cv.is_prerelease and not cv.is_devrelease and cv.local is None :
                        eprint(f"  DEBUG FOR VAULT: Found 1.17.0 equivalent in candidates: {cv} (is_prerelease={cv.is_prerelease})")
                        if cv not in filtered_versions:
                            eprint(f"  DEBUG FOR VAULT: But it was not in filtered_versions. Filtered_versions len: {len(filtered_versions)}")
                        break


    if not filtered_versions:
        eprint(f"  No versions matched filters for {image_name_for_debug} (spec: {specifier_set}).")
        return None
    
    max_ver = max(filtered_versions)
    if image_name_for_debug == "vault":
        eprint(f"  DEBUG FOR VAULT: max(filtered_versions) determined as: {max_ver}")
    
    return str(max_ver)


def main():
    # ... (main function remains largely the same) ...
    try:
        with open("image_references.json", 'r') as f:
            images_data = json.load(f)
    except FileNotFoundError:
        eprint("Error: image_references.json not found.")
        return
    except json.JSONDecodeError:
        eprint("Error: Could not decode image_references.json.")
        return

    try:
        with open(".github/renovate.json5", 'r') as f:
            renovate_config = json5.load(f)
    except FileNotFoundError:
        eprint("Warning: .github/renovate.json5 not found. Proceeding without rules.")
        renovate_config = {} 
    except Exception as e:
        eprint(f"Error parsing .github/renovate.json5: {e}")
        renovate_config = {}

    package_rules = renovate_config.get("packageRules", [])
    proposed_updates = []
    processed_image_names = {} 

    for item in images_data:
        file_path = item["file_path"]
        image_name = item["image_name"]
        current_version_str = str(item["image_tag"]) 

        eprint(f"\nProcessing: {image_name}:{current_version_str} (from {file_path})")

        if current_version_str.lower().startswith("sha256:"):
            eprint(f"  Skipping update check: Current version is a digest: {current_version_str}")
            proposed_updates.append({
                "filePath": file_path, "imageName": image_name, "currentVersion": current_version_str,
                "newVersion": current_version_str, "updateNeeded": False,
                "reason": "Current version is a digest."
            })
            continue
        
        current_semver = None
        try:
            parsed_tag = current_version_str[1:] if current_version_str.startswith('v') else current_version_str
            current_semver = parse_version(parsed_tag)
        except InvalidVersion:
            eprint(f"  Current version '{current_version_str}' for {image_name} is not a standard semantic version.")

        applicable_rule = None
        for rule in package_rules:
            if "matchPackagePatterns" in rule:
                for pattern_str in rule["matchPackagePatterns"]:
                    try:
                        if re.search(pattern_str, image_name):
                            applicable_rule = rule
                            eprint(f"  Found matching Renovate rule for {image_name} with pattern '{pattern_str}'")
                            break
                    except re.error as e:
                        eprint(f"  Regex error for pattern '{pattern_str}': {e}")
            if applicable_rule:
                break
        
        specifier_set = None
        rule_reason_parts = ["No specific rule found."]
        if applicable_rule:
            rule_reason_parts = [f"Rule pattern '{applicable_rule.get('matchPackagePatterns')}' matched."]
            if "allowedVersions" in applicable_rule:
                specifier_set = parse_allowed_versions(applicable_rule["allowedVersions"])
                if specifier_set:
                    rule_reason_parts.append(f"Allowed versions: '{applicable_rule['allowedVersions']}' (parsed as '{specifier_set}').")
                    eprint(f"  Applied rule for {image_name}: allowedVersions='{applicable_rule['allowedVersions']}' parsed as '{specifier_set}'")
                else:
                    rule_reason_parts.append(f"Failed to parse allowedVersions for {image_name}: '{applicable_rule['allowedVersions']}'.")
                    eprint(f"  Rule found for {image_name} but failed to parse allowedVersions: '{applicable_rule['allowedVersions']}'")
        
        tags = None
        effective_image_name_for_crane = image_name 
        if image_name in processed_image_names:
            tags, effective_image_name_for_crane = processed_image_names[image_name]
            eprint(f"  Using cached tags for {image_name} (effective name for crane: {effective_image_name_for_crane})")
        else:
            tags, effective_image_name_for_crane = get_tags_from_registry(image_name)
            processed_image_names[image_name] = (tags, effective_image_name_for_crane)

        if tags is None:
            eprint(f"  Could not fetch tags for {effective_image_name_for_crane}. Skipping version check.")
            proposed_updates.append({
                "filePath": file_path, "imageName": image_name, "currentVersion": current_version_str,
                "newVersion": "Error: Could not fetch tags", "updateNeeded": False,
                "reason": f"Failed to fetch tags for {effective_image_name_for_crane}."
            })
            continue

        latest_allowed_version_str = get_latest_matching_version(tags, image_name, specifier_set, current_version_str)

        update_needed = False
        new_version_display = current_version_str
        
        if latest_allowed_version_str:
            eprint(f"  For {image_name}: Current version for comparison: {current_semver if current_semver else current_version_str}, Latest matching version from registry: {latest_allowed_version_str}")
            latest_semver = None
            try:
                parsed_latest_tag = latest_allowed_version_str[1:] if latest_allowed_version_str.startswith('v') else latest_allowed_version_str
                latest_semver = parse_version(parsed_latest_tag)
            except InvalidVersion:
                 eprint(f"  Error: latest_allowed_version_str '{latest_allowed_version_str}' for {image_name} from registry is not valid semver. This should not happen.")

            if latest_semver:
                if current_semver: 
                    if latest_semver > current_semver:
                        update_needed = True
                        new_version_display = latest_allowed_version_str 
                        rule_reason_parts.append(f"Latest satisfying version is {latest_allowed_version_str}.")
                    elif latest_semver == current_semver and latest_allowed_version_str != current_version_str and latest_allowed_version_str != ('v' + current_version_str) and ('v'+latest_allowed_version_str) != current_version_str :
                        update_needed = True 
                        new_version_display = latest_allowed_version_str
                        rule_reason_parts.append(f"Proposing canonical version {latest_allowed_version_str} (current: {current_version_str}).")
                    else: 
                        new_version_display = current_version_str 
                        rule_reason_parts.append(f"Already at or above the latest satisfying version ({latest_allowed_version_str}).")
                else: 
                    if latest_allowed_version_str != current_version_str:
                        update_needed = True
                        new_version_display = latest_allowed_version_str
                        rule_reason_parts.append(f"Latest satisfying version is {latest_allowed_version_str} (current is non-standard: {current_version_str}).")
                    else:
                         rule_reason_parts.append(f"Already at version {current_version_str} (non-standard).")
        
        if not latest_allowed_version_str: 
            eprint(f"  No suitable version found for {image_name} matching spec: {specifier_set if specifier_set else 'any stable/compatible'}.")
            rule_reason_parts.append("No suitable version found in registry matching constraints.")
            if specifier_set and current_semver and not specifier_set.contains(current_semver):
                rule_reason_parts.append(f"Current version {current_version_str} VIOLATES rule '{specifier_set}'. No alternative found.")

        final_reason = " ".join(rule_reason_parts)
        if len(rule_reason_parts) > 1 and rule_reason_parts[0] == "No specific rule found.":
            final_reason = " ".join(rule_reason_parts[1:])

        proposed_updates.append({
            "filePath": file_path, "imageName": image_name, "currentVersion": current_version_str,
            "newVersion": new_version_display, "updateNeeded": update_needed,
            "reason": final_reason.strip()
        })

    try:
        with open("image_updates_proposed.json", 'w') as f:
            json.dump(proposed_updates, f, indent=2)
        eprint("\nSuccessfully wrote image_updates_proposed.json")
    except IOError:
        eprint("Error: Could not write image_updates_proposed.json.")


if __name__ == "__main__":
    main()
