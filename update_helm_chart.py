import sys
from ruamel.yaml import YAML

yaml_content = sys.stdin.read()

yaml = YAML()
yaml.preserve_quotes = True
try:
    data = yaml.load(yaml_content)
except Exception as e:
    print(f"Error loading YAML: {e}", file=sys.stderr)
    sys.exit(1)

if 'metadata' in data and isinstance(data['metadata'], dict):
    data['metadata']['name'] = 'huntarr'
else:
    print("Warning: metadata.name not found or metadata is not a dict.", file=sys.stderr)

if 'releaseName' in data:
    data['releaseName'] = 'huntarr'
else:
    print("Warning: releaseName not found.", file=sys.stderr)

# Dump to string and print to stdout
from io import StringIO
string_stream = StringIO()
yaml.dump(data, string_stream)
modified_yaml_content = string_stream.getvalue()
print(modified_yaml_content)
