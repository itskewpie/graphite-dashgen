#!/usr/bin/env python
"""Automates the creation of host dashboards based on existing collectd
metrics.
"""
# Standard library
import argparse
from datetime import date
import glob
import json
import logging
import logging.handlers
import os
import sys
import urllib
# Third-party
import yaml

"""USAGE: %prog [options] PROFILE HOST [HOST...]
"""

log = logging.getLogger('dashgen')
screenhdlr = logging.StreamHandler()
screenfmt = logging.Formatter('%(levelname)s %(message)s')
screenhdlr.setFormatter(screenfmt)
# Allows this code to be reloaded interactively without ending up with
# multiple log handlers
log.handlers = list()
log.addHandler(screenhdlr)


def dash_create():
    """Create dashboard for specified host and dashboard profile."""
    defaults = dashconf['defaults']
    today = date.today().strftime('%FT%T')
    dash_names = dashdef.keys()
    log.info("Dashboards %s" % dash_names)

    dashs = list()
    # dashboard
    for dash_name in dash_names:
        if dash_name == 'cnode{num}':
            for num in range(dashconf['cnode_first'],dashconf['cnode_last']+1):
                num = str('%02d' %num)
                dashs.append(_dash_create(defaults, today, dash_name, num))
        elif dash_name == 'snode{num}':
            for num in range(dashconf['snode_first'],dashconf['snode_last']+1):
                num = str('%02d' %num)
                dashs.append(_dash_create(defaults, today, dash_name, num))
        elif dash_name == 'mnode{num}':
            for num in range(dashconf['mnode_first'],dashconf['mnode_last']+1):
                num = str('%02d' %num)
                dashs.append(_dash_create(defaults, today, dash_name, num))
        else:
            dashs.append(_dash_create(defaults, today, dash_name))

    return dashs

def _dash_create(defaults, today, dash_name, num=None):
    if num:
        display_dash_name = dash_name.replace('{num}', num)
    else:
        display_dash_name = dash_name
    log.info("Dashboard %s" % display_dash_name)
    dash = {'name': display_dash_name,
            'defaultGraphParams': {
                'width': defaults['width'],
                'height': defaults['height'],
                'from': '-%s%s' % (defaults['quantity'], defaults['units']),
                'until': defaults['until'],
                'format': defaults['format'],
            },
            'refreshConfig': {
                'interval': defaults['interval'],
                'enabled': defaults['enabled'],
            },
            'graphs': list(),
            'timeConfig': {
                'startDate': today,
                'endDate': today,
#                'startTime': defaults['startTime'],
#                'endTime': defaults['endTime'],
                'quantity': defaults['quantity'],
                'type': defaults['type'],
                'units': defaults['units'],
#
# seems that the new time handling is less than complete
#
#                'relativeStartUnits': defaults['relativeStartUnits'],
#                'relativeStartQuantity': defaults['relativeStartQuantity'],
#                'relativeUntilUnits': defaults['relativeUntilUnits'],
#                'relativeUntilQuantity': defaults['relativeUntilQuantity'],
            },
            'graphSize': {
                'width': defaults['width'],
                'height': defaults['height'],
            },
            }
    dash['graphs'] = graph_create(dash_name, num)
    return dash

def graph_create(dash_name, num):
    """Create graph for specified host and dashboard profile."""
    graphs = list()
    for name in dashdef[dash_name]['graphs']:
        if num:
            log.info("  Graph: %s" % name.replace('{num}', num))
        else:
            log.info("  Graph: %s" % name)
        graph = list()
        # Skip undefined graphs
        if name not in graphdef.keys():
            log.error("%s not found in graphdef.yml" % name)
            continue
        
        graph_object = dict(graphdef[name])
        graph = graph_compile(name, graph_object, None, num)
        if len(graph) > 0:
            graphs.append(graph)

    return graphs


def graph_compile(name, graph_object, metric, num):
    """Finish compiling graph."""
    # Graphs consist of 3 parts
    #   1. graph_targets
    #   2. graph_object
    #   3. graph_render
    color_combined = dashconf['color_combined']
    color_free = dashconf['color_free']
    # target
    templates = graph_object.pop('target')
    target_object = list()
    target_pairs = list()
    for template in templates:
        if num:
            template = template.replace('{num}', num)
        if template.find('mgmt_domain') == -1:
            template = template.replace('{domain}', dashconf['domain'])
        else:
            template = template.replace('{mgmt_domain}', dashconf['mgmt_domain'])
        target = template % {'color_combined': color_combined,
                             'color_free': color_free,
                             'metric': metric,
                             }
        target_object.append(target)
        target_pairs.append(('target', target))
    graph_targets = urllib.urlencode(target_pairs)
    # title
    if 'title' in graph_object.keys():
        graph_object['title'] = graph_object['title'] % {'metric': metric}
    else:
        if num:
            graph_object['title'] = name.replace('{num}', num)
        else:
            graph_object['title'] = name
    graph_object['title'] = graph_object['title'].replace('-', '.')
    # build graph_render
    graph_render = "/render?%s&%s" % (urllib.urlencode(graph_object),
                                      graph_targets)
    # add target(s) to graph_object
    graph_object['target'] = target_object
    return [graph_targets, graph_object, graph_render]


def dash_save(dashs):
    """Save dashboard using Graphite libraries."""
    # Graphite libraries
    sys.path.append(dashconf['webapp_path'])
    os.environ['DJANGO_SETTINGS_MODULE'] = "graphite.settings"
    from graphite.dashboard.models import Dashboard

    for dash in dashs:
        dash_name = dash['name']
        dash_state = str(json.dumps(dash))
        try:
            dashboard = Dashboard.objects.get(name=dash_name)
        except Dashboard.DoesNotExist:
            dashboard = Dashboard.objects.create(name=dash_name, state=dash_state)
        else:
            dashboard.state = dash_state
            dashboard.save()


def set_log_level(args):
    global log
    """Set the logging level."""
    loglevel = args.verbose - args.quiet
    if loglevel >= 2:
        log.setLevel(logging.DEBUG)
    elif loglevel == 1:
        log.setLevel(logging.INFO)
    elif loglevel == 0:
        log.setLevel(logging.WARN)
    elif loglevel < 0:
        log.setLevel(logging.CRITICAL)


def parser_setup():
    """Instantiate, configure, and return an argarse instance."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-c", "--config-dir", default=".",
                    help="Configuration directory. Contains YAML configuration"
                         "files.")
    ap.add_argument("-v", "--verbose", action="count", default=1,
                    help="Print copious debugging info.")
    ap.add_argument("-q", "--quiet", action="count", default=0,
                    help="Suppress output. -qq to suppress ALL output.")
    return ap


def main():
    global dashconf, dashdef, graphdef
    # Command Line Options
    ap = parser_setup()
    args = ap.parse_args()
    set_log_level(args)

    # read yaml configuration files
    dashconf = yaml.safe_load(open('%s/dashconf.yml' % args.config_dir, 'r'))
    dashdef = yaml.safe_load(open('%s/dashdef.yml' % args.config_dir, 'r'))
    graphdef = yaml.safe_load(open('%s/graphdef.yml' % args.config_dir, 'r'))

    dashs = dash_create()
    dash_save(dashs)


if __name__ == "__main__":
    main()
