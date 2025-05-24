import sys
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import LiteralScalarString

yaml_content = sys.stdin.read()

yaml = YAML()
yaml.preserve_quotes = True
# yaml.indent(mapping=2, sequence=4, offset=2) 

try:
    data = yaml.load(yaml_content)
except Exception as e:
    print(f"Error loading YAML: {e}", file=sys.stderr)
    sys.exit(1)

# a. Rename controllers.huntarr to controllers.cleanuperr
if 'controllers' in data and isinstance(data['controllers'], CommentedMap):
    if 'huntarr' in data['controllers']: # Copied from huntarr
        controller_data = data['controllers'].pop('huntarr')
        new_controllers_map = CommentedMap()
        new_controllers_map['cleanuperr'] = controller_data
        for k, v in data['controllers'].items():
            if k != 'huntarr':
                new_controllers_map[k] = v
        data['controllers'] = new_controllers_map
        print("Renamed controllers.huntarr to controllers.cleanuperr", file=sys.stderr)
    else:
        print("Warning: controllers.huntarr not found.", file=sys.stderr)
else:
    print("Warning: 'controllers' map not found.", file=sys.stderr)

# Ensure path to cleanuperr controller exists
cleanuperr_controller = None
if 'controllers' in data and 'cleanuperr' in data['controllers']:
    cleanuperr_controller = data['controllers']['cleanuperr']

if cleanuperr_controller and 'containers' in cleanuperr_controller and 'app' in cleanuperr_controller['containers']:
    app_container = cleanuperr_controller['containers']['app']

    # b. Update image repository and tag
    if 'image' in app_container and isinstance(app_container['image'], CommentedMap):
        app_container['image']['repository'] = 'ghcr.io/roxedus/cleanuperr'
        app_container['image']['tag'] = 'latest'
        print("Updated image repository and tag for cleanuperr.", file=sys.stderr)
    else:
        print("Warning: image section not found in cleanuperr.containers.app.", file=sys.stderr)

    # c. Update env vars
    if 'env' in app_container and isinstance(app_container['env'], CommentedMap):
        # Keep TZ, remove others if they are Huntarr/Sonarr specific like PUID/PGID or SONARR__PORT
        # The prompt asks to remove huntarr-specific ones. SONARR__PORT was from sonarr.
        # Cleanuperr doesn't seem to use PUID/PGID if podSecurityContext is used.
        # It might need specific env vars for its own config, but the prompt focuses on removal.
        env_to_keep = CommentedMap()
        if 'TZ' in app_container['env']:
            env_to_keep['TZ'] = app_container['env']['TZ']
        else: # Add if not present
            env_to_keep['TZ'] = "America/Chicago" 
        
        # Remove SONARR__PORT if present from previous copy
        # app_container['env'].pop('SONARR__PORT', None) # This was in huntarr, remove it.
        # The new env_to_keep strategy handles this implicitly.
        
        app_container['env'] = env_to_keep
        print(f"Updated env vars for cleanuperr. Kept/ensured TZ.", file=sys.stderr)
    else:
        print("Warning: env map not found in cleanuperr.containers.app.", file=sys.stderr)
else:
    print("Warning: controllers.cleanuperr.containers.app path not fully found for image/env updates.", file=sys.stderr)

# d. Update service.app
if 'service' in data and 'app' in data['service'] and isinstance(data['service']['app'], CommentedMap):
    service_app = data['service']['app']
    service_app['controller'] = 'cleanuperr'
    if 'ports' in service_app and 'http' in service_app['ports'] and isinstance(service_app['ports']['http'], CommentedMap):
        service_app['ports']['http']['port'] = 5000
        print("Updated service.app controller and port for cleanuperr.", file=sys.stderr)
    else:
        print("Warning: service.app.ports.http not found for cleanuperr.", file=sys.stderr)
else:
    print("Warning: service.app not found for cleanuperr.", file=sys.stderr)

# e. Update ingress.app
if 'ingress' in data and 'app' in data['ingress'] and isinstance(data['ingress']['app'], CommentedMap):
    ingress_app = data['ingress']['app']
    new_host = 'cleanuperr.sievert.fun'
    
    if 'hosts' in ingress_app and isinstance(ingress_app['hosts'], CommentedSeq) and len(ingress_app['hosts']) > 0:
        if isinstance(ingress_app['hosts'][0], CommentedMap):
            ingress_app['hosts'][0]['host'] = new_host
    if 'annotations' in ingress_app and isinstance(ingress_app['annotations'], CommentedMap):
        ingress_app['annotations']['external-dns.alpha.kubernetes.io/internal-hostname'] = new_host
    if 'tls' in ingress_app and isinstance(ingress_app['tls'], CommentedSeq) and len(ingress_app['tls']) > 0:
        if isinstance(ingress_app['tls'][0], CommentedMap):
            ingress_app['tls'][0]['secretName'] = 'cleanuperr-tls'
            if 'hosts' in ingress_app['tls'][0] and isinstance(ingress_app['tls'][0]['hosts'], CommentedSeq) and \
               len(ingress_app['tls'][0]['hosts']) > 0:
                ingress_app['tls'][0]['hosts'][0] = new_host
    print("Updated ingress.app fields for cleanuperr.", file=sys.stderr)
else:
    print("Warning: ingress.app not found for cleanuperr.", file=sys.stderr)

# f. Update persistence
if 'persistence' in data and isinstance(data['persistence'], CommentedMap):
    # Config volume (assuming it's 'config') - ensure it's as specified
    if 'config' in data['persistence'] and isinstance(data['persistence']['config'], CommentedMap):
        config_vol = data['persistence']['config']
        config_vol['enabled'] = True
        config_vol['type'] = 'persistentVolumeClaim'
        config_vol['accessMode'] = 'ReadWriteOnce'
        config_vol['storageClass'] = 'local-path' # As per prompt
        config_vol['size'] = '1Gi'
        if 'globalMounts' not in config_vol or not isinstance(config_vol['globalMounts'], CommentedSeq) or len(config_vol['globalMounts']) == 0:
            config_vol['globalMounts'] = CommentedSeq([CommentedMap({'path': '/config'})])
        else:
            config_vol['globalMounts'][0]['path'] = '/config'
        print("Ensured persistence.config settings for cleanuperr.", file=sys.stderr)
    else:
        print("Warning: persistence.config not found for cleanuperr.", file=sys.stderr)

    # Media volume - set enabled to false
    if 'media' in data['persistence'] and isinstance(data['persistence']['media'], CommentedMap):
        data['persistence']['media']['enabled'] = False
        # existingClaim can remain or be removed, prompt implies just disabling.
        # If it was smb-huntarr, it's fine to leave it if disabled.
        print("Set persistence.media.enabled to false for cleanuperr.", file=sys.stderr)
    # else: # If media persistence was not copied, that's fine.
else:
    print("Warning: 'persistence' map not found for cleanuperr.", file=sys.stderr)

# g. Add 'files' for config.yaml
config_yaml_content = """\
# Cleanuperr config.yaml placeholder
# Refer to Cleanuperr documentation to configure connections to Sonarr, Radarr, etc.
# Example structure (verify with actual Cleanuperr docs):
# general:
#   timezone: "America/Chicago" # Should match TZ env
# sonarr:
#   - name: Sonarr Instance
#     url: http://sonarr.sonarr.svc.cluster.local:8989 # Or your Sonarr URL
#     apiKey: YOUR_SONARR_API_KEY
# radarr:
#   - name: Radarr Instance
#     url: http://radarr.radarr.svc.cluster.local:7878 # Or your Radarr URL
#     apiKey: YOUR_RADARR_API_KEY
"""
if 'files' not in data:
    data['files'] = CommentedMap()

data['files']['config.yaml'] = CommentedMap({
    'enabled': True,
    'content': LiteralScalarString(config_yaml_content)
})
print("Added files.config.yaml section for cleanuperr.", file=sys.stderr)

# h. Ensure podSecurityContext
expected_psc = {'runAsUser': 65534, 'runAsGroup': 65534, 'fsGroup': 65534, 'fsGroupChangePolicy': 'OnRootMismatch'}
if 'podSecurityContext' in data and isinstance(data['podSecurityContext'], CommentedMap):
    psc = data['podSecurityContext']
    match = all(psc.get(k) == v for k, v in expected_psc.items()) and len(psc) == len(expected_psc)
    if match:
        print("Verified podSecurityContext for cleanuperr.", file=sys.stderr)
    else:
        print(f"Warning: podSecurityContext for cleanuperr ({psc}) does not match expected. Overwriting.", file=sys.stderr)
        data['podSecurityContext'] = CommentedMap(expected_psc)
else:
    print("Warning: podSecurityContext not found for cleanuperr. Adding.", file=sys.stderr)
    data['podSecurityContext'] = CommentedMap(expected_psc)


# Dump the full modified YAML to stdout
from io import StringIO
string_stream = StringIO()
yaml.dump(data, string_stream)
modified_yaml_content = string_stream.getvalue()
print(modified_yaml_content)
