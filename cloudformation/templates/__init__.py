import os
import yaml

def config_stack(stack_name, template_name, region):
  return {
    'stack': stack_name,
    'template_name': template_name,
    'region': region,
  }


def merge(a, b, path=None, update=True):
  "http://stackoverflow.com/questions/7204805/python-dictionaries-of-dictionaries-merge"
  "merges b into a"
  if path is None: path = []
  for key in b:
    if key in a:
      if isinstance(a[key], dict) and isinstance(b[key], dict):
        merge(a[key], b[key], path + [str(key)])
      elif a[key] == b[key]:
        pass # same leaf value
      elif isinstance(a[key], list) and isinstance(b[key], list):
        # assume we don't have dictionaries inside lists
        a[key] = list(set(a[key] + b[key]))
      elif update:
        a[key] = b[key]
      else:
        raise Exception('Conflict at %s' % '.'.join(path + [str(key)]))
    else:
      a[key] = b[key]
  return a


def read_yaml_file(filename):
  with open(filename, 'r') as f:
    return yaml.load(f) or {}


def config(stack_name):
  # Read the stack configuration just to get the template and region name
  stack = read_yaml_file("configuration/stacks/%s/config.yaml" % stack_name)
  template_name = stack['template_name'] if 'template_name' in stack else None
  region = stack['region'] if 'region' in stack else None

  stack_config = config_stack(stack_name, template_name, region)

  config_files = [
    "configuration/templates/config.yaml",
    "configuration/templates/%s/config.yaml" % template_name,
    "configuration/stacks/%s/config.yaml" % stack_name,
  ]

  for config_file in config_files:
    if os.path.exists(config_file):
      stack_config = merge(stack_config, read_yaml_file(config_file))

  return stack_config
