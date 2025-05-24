import sys
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

yaml_content = sys.stdin.read()

yaml = YAML()
yaml.preserve_quotes = True
# yaml.indent(mapping=2, sequence=4, offset=2) # Default indentation is usually fine

try:
    data = yaml.load(yaml_content)
except Exception as e:
    print(f"Error loading YAML: {e}", file=sys.stderr)
    sys.exit(1)

# a. Rename controllers.sonarr to controllers.huntarr
if 'controllers' in data and isinstance(data['controllers'], CommentedMap):
    if 'sonarr' in data['controllers']:
        sonarr_controller_data = data['controllers'].pop('sonarr')
        # Insert 'huntarr' at a specific position if desired, or just add it.
        # For now, just add it. Order might change if it was ordered dict.
        # To preserve order better, one might rebuild the controllers map.
        # A simple way for now:
        new_controllers_map = CommentedMap()
        if 'huntarr' in data['controllers']: # Should not happen if renaming
             print("Warning: 'huntarr' controller already exists before rename.", file=sys.stderr)
        new_controllers_map['huntarr'] = sonarr_controller_data
        for k, v in data['controllers'].items(): # Add other controllers if any
            if k != 'sonarr': # Should be already popped
                new_controllers_map[k] = v
        data['controllers'] = new_controllers_map
        print("Renamed controllers.sonarr to controllers.huntarr", file=sys.stderr)
    else:
        print("Warning: controllers.sonarr not found.", file=sys.stderr)
else:
    print("Warning: 'controllers' map not found.", file=sys.stderr)


# Ensure path to huntarr controller exists for subsequent operations
huntarr_controller = None
if 'controllers' in data and 'huntarr' in data['controllers']:
    huntarr_controller = data['controllers']['huntarr']

if huntarr_controller and 'containers' in huntarr_controller and 'app' in huntarr_controller['containers']:
    app_container = huntarr_controller['containers']['app']

    # b. Update image repository and tag
    if 'image' in app_container and isinstance(app_container['image'], CommentedMap):
        app_container['image']['repository'] = 'hotio/huntarr'
        app_container['image']['tag'] = 'release' # ruamel.yaml handles type preservation
        print("Updated image repository and tag.", file=sys.stderr)
    else:
        print("Warning: image section not found or not a map in huntarr.containers.app.", file=sys.stderr)

    # c. Update env vars
    if 'env' in app_container and isinstance(app_container['env'], CommentedMap):
        keys_to_remove = ['SONARR__INSTANCE_NAME', 'SONARR__APPLICATION_URL', 'SONARR__LOG_LEVEL']
        current_env = CommentedMap() # Build a new map to preserve order and comments of remaining items
        
        original_tz_value = None # Keep original TZ if it exists
        if 'TZ' in app_container['env']:
            original_tz_value = app_container['env']['TZ']

        for key, value in app_container['env'].items():
            if key not in keys_to_remove:
                current_env[key] = value
        
        # Ensure TZ is present
        if 'TZ' not in current_env and original_tz_value is not None: # Add it back if removed during rebuild
            current_env['TZ'] = original_tz_value
        elif 'TZ' not in current_env: # If it was never there, add default (as per Sonarr)
             current_env['TZ'] = 'America/Chicago'


        app_container['env'] = current_env
        print(f"Updated env vars. Removed: {keys_to_remove}. Ensured TZ.", file=sys.stderr)
    else:
        print("Warning: env map not found in huntarr.containers.app.", file=sys.stderr)
else:
    print("Warning: controllers.huntarr.containers.app path not fully found for image/env updates.", file=sys.stderr)


# d. Update service.app
if 'service' in data and 'app' in data['service'] and isinstance(data['service']['app'], CommentedMap):
    service_app = data['service']['app']
    service_app['controller'] = 'huntarr'
    if 'ports' in service_app and 'http' in service_app['ports'] and isinstance(service_app['ports']['http'], CommentedMap):
        service_app['ports']['http']['port'] = 9000 # ruamel.yaml handles type
        print("Updated service.app controller and port.", file=sys.stderr)
    else:
        print("Warning: service.app.ports.http not found or not a map.", file=sys.stderr)
else:
    print("Warning: service.app not found or not a map.", file=sys.stderr)


# e. Update ingress.app
if 'ingress' in data and 'app' in data['ingress'] and isinstance(data['ingress']['app'], CommentedMap):
    ingress_app = data['ingress']['app']
    new_host = 'huntarr.sievert.fun'
    
    if 'hosts' in ingress_app and isinstance(ingress_app['hosts'], CommentedSeq) and len(ingress_app['hosts']) > 0:
        if isinstance(ingress_app['hosts'][0], CommentedMap):
            ingress_app['hosts'][0]['host'] = new_host
        else:
             print("Warning: ingress.app.hosts[0] is not a map.", file=sys.stderr)
    else:
        print("Warning: ingress.app.hosts not found or empty.", file=sys.stderr)

    if 'annotations' in ingress_app and isinstance(ingress_app['annotations'], CommentedMap):
        ingress_app['annotations']['external-dns.alpha.kubernetes.io/internal-hostname'] = new_host
    else:
        print("Warning: ingress.app.annotations not found or not a map.", file=sys.stderr)

    if 'tls' in ingress_app and isinstance(ingress_app['tls'], CommentedSeq) and len(ingress_app['tls']) > 0:
        if isinstance(ingress_app['tls'][0], CommentedMap):
            ingress_app['tls'][0]['secretName'] = 'huntarr-tls'
            if 'hosts' in ingress_app['tls'][0] and isinstance(ingress_app['tls'][0]['hosts'], CommentedSeq) and \
               len(ingress_app['tls'][0]['hosts']) > 0:
                ingress_app['tls'][0]['hosts'][0] = new_host
            else:
                print("Warning: ingress.app.tls[0].hosts not found or empty.", file=sys.stderr)
        else:
             print("Warning: ingress.app.tls[0] is not a map.", file=sys.stderr)
    else:
        print("Warning: ingress.app.tls not found or empty.", file=sys.stderr)
    print("Updated ingress.app fields.", file=sys.stderr)
else:
    print("Warning: ingress.app not found or not a map.", file=sys.stderr)


# f. Update persistence.media
if 'persistence' in data and 'media' in data['persistence'] and \
   isinstance(data['persistence']['media'], CommentedMap):
    data['persistence']['media']['existingClaim'] = 'smb-huntarr'
    print("Updated persistence.media.existingClaim.", file=sys.stderr)
else:
    print("Warning: persistence.media.existingClaim not found.", file=sys.stderr)

# g. Ensure podSecurityContext (no changes needed if copied correctly, this is a check)
if 'podSecurityContext' in data and isinstance(data['podSecurityContext'], CommentedMap):
    psc = data['podSecurityContext']
    expected_psc = {'runAsUser': 65534, 'runAsGroup': 65534, 'fsGroup': 65534, 'fsGroupChangePolicy': 'OnRootMismatch'}
    match = True
    for k, v in expected_psc.items():
        if psc.get(k) != v:
            match = False
            break
    if match and len(psc) == len(expected_psc):
        print("Verified podSecurityContext.", file=sys.stderr)
    else:
        print(f"Warning: podSecurityContext ({psc}) does not match expected ({expected_psc}). Overwriting to ensure.", file=sys.stderr)
        data['podSecurityContext'] = CommentedMap(expected_psc) # Enforce it if different
else:
    print("Warning: podSecurityContext not found. Adding.", file=sys.stderr)
    data['podSecurityContext'] = CommentedMap({'runAsUser': 65534, 'runAsGroup': 65534, 'fsGroup': 65534, 'fsGroupChangePolicy': 'OnRootMismatch'})


# Dump the full modified YAML to stdout
from io import StringIO
string_stream = StringIO()
yaml.dump(data, string_stream)
modified_yaml_content = string_stream.getvalue()
print(modified_yaml_content)
