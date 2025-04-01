#
# -*- coding: utf-8 -*-
# Copyright 2024 Dell Inc. or its subsidiaries. All Rights Reserved
# GNU General Public License v3.0+
# (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
"""
The sonic_ospfv3_area class
It is in this file where the current configuration (as list)
is compared to the provided configuration (as list) and the command set
necessary to bring the current configuration to it's desired end-state is
created
"""
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

from copy import deepcopy
from ansible_collections.ansible.netcommon.plugins.module_utils.network.common.cfg.base import (
    ConfigBase,
)
from ansible_collections.ansible.netcommon.plugins.module_utils.network.common.utils import (
    to_list,
    validate_config,
)
from ansible_collections.dellemc.enterprise_sonic.plugins.module_utils.network.sonic.utils.utils \
    import (
        get_diff,
        update_states,
        to_request,
        edit_config,
        remove_empties,
        remove_empties_from_list
    )
from ansible_collections.dellemc.enterprise_sonic.plugins.module_utils.network.sonic.utils.formatted_diff_utils import (
    __DELETE_OP_DEFAULT,
    __DELETE_SAME_LEAFS_THEN_CONFIG_IF_NO_NON_KEY_LEAF,
    get_new_config,
    get_formatted_config_diff
)
from ansible_collections.dellemc.enterprise_sonic.plugins.module_utils.network.sonic.facts.facts import Facts
from ansible_collections.dellemc.enterprise_sonic.plugins.module_utils.network.sonic.utils.utils import (
    remove_none
)


def list_generate_deleted_config_helper(key_set, command, existing_conf, delete_handler):
    '''helps with delete state generate config for this module. takes config that are list structures and
    if there is matching entry in commands, calls passed in handler on the item. Does some preprocessing, if
    commands is empty list empty out current config.'''
    if command == []:
        # command being empty list means clear list
        return []
    if len(existing_conf) == 0:
        # early return there's nothing to delete
        return existing_conf
    if key_set:
        command_dict = {tuple(c[field] for field in key_set): c for c in command}
        existing_dict = {tuple(c[field] for field in key_set): c for c in existing_conf}
    else:
        command_dict = {c: c for c in command}
        existing_dict = {c: c for c in existing_conf}

    new_conf = []
    # for every existing item, either deleting or not
    # keys only in command and not existing do not affect anything
    for e_key, e_data in existing_dict.items():
        if e_key in command_dict:
            # existing has a matching command for deleting, process it
            nu, new_item = delete_handler(key_set, command_dict[e_key], e_data)
            if new_item:
                # filter out if whole item was deleted. only keep items with something leftover
                new_conf.append(new_item)
        else:
            # existing has no matching command for deleting, can't be changed so keep it
            new_conf.append(e_data)
    return new_conf


def derive_delete_area(key_set, command, exist_conf):

    if len(command) == 2:
        # implementation is specifying just area id keys means delete the area
        return True, {}

    # default delete seems to be unable to handle case where existing config has many keys, and command
    # only specifies a list to clear by providing an empty list, and no other keys. Not all existing keys need
    # to be deleted, but default thinks existing should be cleared

    new_conf = deepcopy(exist_conf)
    command_data_keys = [key for key in command.keys() if key not in ["ranges", "stub", "vrf_name", "area_id"]]
    exist_data_keys = [key for key in exist_conf.keys() if key not in ["ranges", "stub", "vrf_name", "area_id"]]
    both = set(command_data_keys).intersection(exist_data_keys)
    if both:
        for k in both:
            if command[k] == exist_conf[k]:
                del new_conf[k]

    if "ranges" in command and "ranges" in exist_conf:
        new_conf["ranges"] = list_generate_deleted_config_helper({"prefix"}, command["ranges"], exist_conf["ranges"], derive_delete_key)
    if "stub" in command and "stub" in exist_conf:
        nu, new_conf["stub"] = __DELETE_OP_DEFAULT({}, command["stub"], exist_conf["stub"])
    new_conf = remove_empties(new_conf)
    if not new_conf or len(new_conf) == 2:
        # area after deleting everything specified is empty or just the keys, disregard it
        return True, {}
    else:
        return True, new_conf

def derive_delete_key(key_set, command, exist_conf):
    if command.keys() == key_set:
        return True, {}
    else:
        return __DELETE_SAME_LEAFS_THEN_CONFIG_IF_NO_NON_KEY_LEAF(key_set, command, exist_conf)


TEST_KEYS_generate_config = [
    {"config": {"area_id": "", "vrf_name": "", "__delete_op": derive_delete_area}},
    {"ranges": {"prefix": "", "__delete_op": derive_delete_key}}
]

OSPF_URI = "data/openconfig-network-instance:network-instances/network-instance={vrf_name}/protocols/protocol=OSPF3,ospfv3/ospfv3"
OSPF_KEY_EXT = "openconfig-ospfv3-ext:"
OSPF_AREA_GLOBAL_URI = "/global/openconfig-ospfv3-ext:inter-area-propagation-policies/inter-area-policy={area_id}"
OSPF_AREA_ATTRIBUTES = {
    'area_id': "/areas/area={area_id}",
    'filter_list_in': OSPF_AREA_GLOBAL_URI + "/filter-list-in/config/name",
    'filter_list_out': OSPF_AREA_GLOBAL_URI + "/filter-list-out/config/name",
    'nssa': {
        'enabled': "/areas/area={area_id}/openconfig-ospfv3-ext:nssa/config/enable",
        'no_summary': "/areas/area={area_id}/openconfig-ospfv3-ext:nssa/config/no-summary",
        'default_originate': {
            'enabled': "/areas/area={area_id}/openconfig-ospfv3-ext:nssa/config/default-route-originate",
            'metric': "/areas/area={area_id}/openconfig-ospfv3-ext:nssa/config/default-route-metric",
            'metric_type': "/areas/area={area_id}/openconfig-ospfv3-ext:nssa/config/default-route-metric-type"
        },
        'ranges': {
            'advertise': "/areas/area={area_id}/openconfig-ospfv3-ext:nssa/ranges/range={address_prefix}/config/advertise",
            'prefix': "/areas/area={area_id}/openconfig-ospfv3-ext:nssa/ranges/range={address_prefix}/config/address-prefix",
            'cost': "/areas/area={area_id}/openconfig-ospfv3-ext:nssa/ranges/range={address_prefix}/config/cost"
        }
    },
    'stub': {
        'enabled': "/areas/area={area_id}/openconfig-ospfv3-ext:stub/config/enable",
        'no_summary': "/areas/area={area_id}/openconfig-ospfv3-ext:stub/config/no-summary",
    },
    'ranges': {
        'advertise': OSPF_AREA_GLOBAL_URI + "/ranges/range={address_prefix}/config/advertise",
        'prefix': OSPF_AREA_GLOBAL_URI + "/ranges/range={address_prefix}/config/address-prefix",
        'cost': OSPF_AREA_GLOBAL_URI + "/ranges/range={address_prefix}/config/metric"
    }
}

class Ospfv3_area(ConfigBase):
    """
    The sonic_ospfv3_area class
    """

    gather_subset = [
        '!all',
        '!min',
    ]

    gather_network_resources = [
        'ospfv3_area',
    ]

    TEST_KEYS = [
        {"config": {"area_id": "", "vrf_name": ""}},
        {"ranges": {"prefix": ""}}
    ]

    def __init__(self, module):
        super(Ospfv3_area, self).__init__(module)

    def get_ospfv3_area_facts(self):
        """ Get the 'facts' (the current configuration)

        :rtype: A list
        :returns: The current configuration as a list of areas' config
        """
        facts, _warnings = Facts(self._module).get_facts(self.gather_subset, self.gather_network_resources)
        ospfv3_area_facts = facts['ansible_network_resources'].get('ospfv3_area')
        if not ospfv3_area_facts:
            return []
        return ospfv3_area_facts["config"]

    def execute_module(self):
        """ Execute the module

        :rtype: A dictionary
        :returns: The result from module execution
        """
        result = {'changed': False}
        warnings = []
        commands = []
        existing_ospfv3_area_facts = self.get_ospfv3_area_facts()
        commands, requests = self.set_config(existing_ospfv3_area_facts)
        if commands and len(requests) > 0:
            if not self._module.check_mode:
                try:
                    edit_config(self._module, to_request(self._module, requests))
                except ConnectionError as exc:
                    self._module.fail_json(msg=str(exc), code=exc.errno)
            result['changed'] = True
        result['commands'] = commands

        result['before'] = existing_ospfv3_area_facts
        new_config = deepcopy(existing_ospfv3_area_facts)
        # just used for diff mode, setting it to a default value that would show no differences. If there are changes then set to changed value

        if self._module.check_mode:
            new_config = get_new_config(commands, existing_ospfv3_area_facts,
                                        TEST_KEYS_generate_config)
            result['after(generated)'] = new_config
        elif result['changed']:
            new_config = self.get_ospfv3_area_facts()
            result['after'] = new_config
        if self._module._diff:
            new_config.sort(key=lambda x: (x['area_id'], x['vrf_name']))
            existing_ospfv3_area_facts.sort(key=lambda x: (x['area_id'], x['vrf_name']))
            result['config_diff'] = get_formatted_config_diff(existing_ospfv3_area_facts,
                                                              new_config,
                                                              self._module._verbosity)
        result['warnings'] = warnings
        return result

    def set_config(self, existing_ospfv3_area_facts):
        """ Collect the configuration from the args passed to the module,
            collect the current configuration (as a dict from facts)

        :rtype: A list
        :returns: the commands necessary to migrate the current configuration
                  to the desired configuration
        """
        want = self._module.params['config']
        have = existing_ospfv3_area_facts

        resp = self.set_state(want, have)
        return to_list(resp)

    def set_state(self, want, have):
        """ Select the appropriate function based on the state provided

        :param want: the desired configuration as a list
        :param have: the current configuration as a list
        :rtype: A tuple
        :returns: the commands necessary to migrate the current configuration
                  to the desired configuration, and REST requests that do it
        """
        commands, requests = [], []
        state = self._module.params['state']
        want = self.validate_normalize_config(want, have, state)
        if state in ('overridden', 'replaced'):
            commands, requests = self._state_replaced_or_overridden(want, have)
        elif state == 'deleted':
            commands, requests = self._state_deleted(want, have)
        elif state == 'merged':
            commands, requests = self._state_merged(want, have)
        return commands, requests

    def _state_merged(self, want, have):
        """ The command generator when state is merged

        :rtype: A tuple of lists
        :returns: A list of the commands and state needed to merge the user-specified
                  new and modified configuration commands into the current
                  configuration, and a list of the corresponding requests that
                  need to be sent to the device to make the specified changes
        """
        commands = remove_empties_from_list(get_diff(want, have, self.TEST_KEYS))
        requests = self.create_ospfv3_area_requests_from_commands(commands)

        if commands and len(requests) > 0:
            commands = update_states(commands, 'merged')
        else:
            commands = []

        return commands, requests

    def _state_deleted(self, want, have):
        """ The command generator when state is deleted

        :rtype: A tuple of lists
        :returns: A list of the commands and state needed to delete the user-specified
                  configuration commands from the current
                  configuration, and a list of the corresponding requests that
                  need to be sent to the device to make the specified changes
        """
        commands, requests = [], []
        is_delete_all = False
        if not want:
            new_want = have
            is_delete_all = True
        else:
            new_want = want

        commands, requests = self.get_delete_ospfv3_area_requests_commands(new_want, have, is_delete_all)

        if commands and len(requests) > 0:
            commands = update_states(commands, 'deleted')
        else:
            commands = []

        return commands, requests

    def _state_replaced_or_overridden(self, want, have):
        """ The command generator when state is replaced or overridden

        :rtype: A tuple of lists
        :returns: A list of what commands and state necessary to migrate the current configuration
                  to the desired configuration, and a list of requests needed to make changes
        """
        commands, requests = [], []
        state = self._module.params['state']
        new_want = self._add_default_values(want)
        add_config, del_config = self._get_replaced_overridden_config(new_want, have, state)
        if del_config and len(del_config) > 0:
            del_requests = self.delete_ospfv3_area_requests_from_commands(del_config, have)
            if len(del_requests) > 0:
                requests.extend(del_requests)
                commands.extend(update_states(del_config, 'deleted'))

        if add_config:
            mod_requests = self.create_ospfv3_area_requests_from_commands(add_config)
            if len(mod_requests) > 0:
                requests.extend(mod_requests)
                commands.extend(update_states(add_config, state))

        return commands, requests

    def _add_default_values(self, conf):
        for config in conf:
            if 'ranges' in config:
                for range_item in config['ranges']:
                    if 'advertise' not in range_item:
                        range_item['advertise'] = True
            if 'nssa' in config and 'ranges' in config['nssa']:
                for range_item in config['nssa']['ranges']:
                    if 'advertise' not in range_item:
                        range_item['advertise'] = True
        return conf

    def validate_normalize_config(self, config, have, state):
        '''validates config and and normalizes format of data. Normalization includes formatting area id, checking setting default cost,
        and filling in auth key information.
        :returns: config object that has been validated and normalized'''
        if not config:
            return []
        config = {"config": config}
        config = remove_none(config)
        # validate_config returns validated user input config. The returned data is based on the
        # argspec definition. At each nested level of the argspec for which the user has specified
        # one or more attributes, the returned data contains added nulls for any attributes that
        # were not specified by the user input.
        config = validate_config(self._module.argument_spec, config)
        # not really using the none values in this module so getting thrown out. Use empty lists for clear
        config = remove_none(config)["config"]
        area_h_keys = {(area["area_id"], area["vrf_name"]): area for area in have}
        for area in config:
            try:
                area['area_id'] = self.format_area_name(area['area_id'])
            except Exception as exc:
                self._module.fail_json(msg=str(exc))

        return config

    def format_area_name(self, area_id):
        """area names in playbook can be single numbers or as four octet numbers, switch works with area names as the latter.
        make sure things are in octect format by applying formatting where needed"""
        if area_id.count(".") < 3:
            area_int = int(area_id)
            return ".".join([str(area_int >> 24 & 0xff), str(area_int >> 16 & 0xff), str(area_int >> 8 & 0xff), str(area_int & 0xff)])
        return area_id

    def get_delete_ospfv3_area_requests_commands(self, want, have, is_delete_all):
        commands, requests = [], []

        for cmd in want:
            vrf_name = cmd.get('vrf_name')
            area_id = cmd.get('area_id')
            match_have = next((cfg for cfg in have if cfg['vrf_name'] == vrf_name and cfg['area_id'] == area_id), None)

            if is_delete_all or len(cmd) == 2:
                if match_have:
                    commands.append({'vrf_name': vrf_name, 'area_id': area_id})
            else:
                del_cmd = {}
                if match_have:
                    for attr in cmd:
                        if attr in ['vrf_name', 'area_id']:
                            continue
                        if attr == 'nssa' or attr == 'stub':
                            if len(cmd[attr]) == 1:
                                del_cmd[attr] = match_have[attr]
                                continue
                            if 'no_summary' in cmd.get(attr, {}) and 'no_summary' in match_have.get(attr, {}):
                                del_cmd.setdefault(attr, {})['no_summary'] = match_have[attr]['no_summary']
                            elif 'default_originate' in cmd.get(attr, {}) and 'default_originate' in match_have.get(attr, {}):
                                del_cmd.setdefault(attr, {})['default_originate'] = match_have[attr]['default_originate']
                            elif 'ranges' in cmd.get(attr, {}) and 'ranges' in match_have.get(attr, {}):
                                range_cmd = self.get_delete_ospfv3_area_ranges_commands(cmd[attr]['ranges'], match_have[attr]['ranges'])
                                if range_cmd:
                                    del_cmd.setdefault(attr, {})['ranges'] = range_cmd
                        elif attr == 'ranges' and match_have.get(attr, []):
                            range_cmd = self.get_delete_ospfv3_area_ranges_commands(cmd[attr], match_have[attr])
                            if range_cmd:
                                del_cmd[attr] = range_cmd
                        elif attr in match_have:
                            del_cmd[attr] = match_have[attr]

                if del_cmd:
                    del_cmd['vrf_name'] = vrf_name
                    del_cmd['area_id'] = area_id
                    commands.append(del_cmd)

        if commands:
            requests = self.delete_ospfv3_area_requests_from_commands(commands, have)

        return commands, requests

    def get_delete_ospfv3_area_ranges_commands(self, want_ranges, have_ranges):
        commands = []
        if len(want_ranges) == 0:
            for range_item in have_ranges:
                commands.append({'prefix': range_item.get('prefix')})
            return commands

        for range_item in want_ranges:
            want_range_prefix = range_item.get('prefix')
            match_have_range = next((cfg for cfg in have_ranges if cfg['prefix'] == want_range_prefix), None)
            if match_have_range:
                if len(range_item) == 1:
                    commands.append({'prefix': want_range_prefix})
                elif len(range_item) == len(match_have_range):
                    commands.append({'prefix': want_range_prefix})
                else:
                    range_cmd = {}
                    for attr in range_item:
                        if attr == 'prefix':
                            continue
                        if attr in match_have_range:
                            range_cmd[attr] = match_have_range[attr]
                    if range_cmd:
                        range_cmd['prefix'] = want_range_prefix
                        commands.append(range_cmd)
        return commands

    def _get_replaced_overridden_config(self, want, have, state):
        add_config, del_config = [], []

        for conf in want:
            vrf_name = conf.get('vrf_name')
            area_id = conf.get('area_id')
            match_have = next((cfg for cfg in have if cfg['vrf_name'] == vrf_name and cfg['area_id'] == area_id), None)

            if not match_have:
                add_config.append(conf)
            else:
                add_cfg, del_cfg = {}, {}
                for attr in conf:
                    if attr in ['vrf_name', 'area_id']:
                        continue
                    if attr not in match_have and attr not in ['nssa', 'stub']:
                        add_cfg[attr] = conf[attr]
                    elif attr == 'ranges':
                        add_range, del_range = self._get_diff_in_ranges(conf[attr], match_have[attr])
                        if add_range:
                            add_cfg[attr] = add_range
                        if del_range:
                            for range_item in del_range:
                                del_cfg.setdefault(attr, []).append({'prefix': range_item['prefix']})
                    elif attr in ['filter_list_in', 'filter_list_out']:
                        if match_have[attr] != conf[attr]:
                            add_cfg[attr] = conf[attr]
                            del_cfg[attr] = match_have[attr]
                    elif attr == 'stub':
                        if 'nssa' in match_have:
                            del_cfg['nssa'] = match_have['nssa']
                            add_cfg[attr] = conf[attr]
                        else:
                            for sub_attr in conf[attr]:
                                if sub_attr not in match_have[attr]:
                                    add_cfg.setdefault(attr, {})[sub_attr] = conf[attr][sub_attr]
                                elif match_have[attr][sub_attr] != conf[attr][sub_attr]:
                                    add_cfg.setdefault(attr, {})[sub_attr] = conf[attr][sub_attr]
                                    del_cfg.setdefault(attr, {})[sub_attr] = match_have[attr][sub_attr]
                            for sub_attr in match_have[attr]:
                                if attr in conf:
                                    if sub_attr not in conf[attr]:
                                        del_cfg.setdefault(attr, {})[sub_attr] = match_have[attr][sub_attr]
                    elif attr == 'nssa':
                        if 'stub' in match_have:
                            del_cfg['stub'] = match_have['stub']
                            add_cfg[attr] = conf[attr]
                        else:
                            for sub_attr in conf[attr]:
                                if sub_attr == 'no_summary':
                                    if 'default_originate' in match_have[attr]:
                                        del_cfg.setdefault(attr, {})['default_originate'] = match_have[attr]['default_originate']
                                        add_cfg.setdefault(attr, {})[sub_attr] = conf[attr][sub_attr]
                                    elif match_have[attr][sub_attr] != conf[attr][sub_attr]:
                                        add_cfg.setdefault(attr, {})[sub_attr] = conf[attr][sub_attr]
                                        del_cfg.setdefault(attr, {})[sub_attr] = match_have[attr][sub_attr]
                                elif sub_attr == 'default_originate':
                                    if 'no_summary' in match_have[attr]:
                                        del_cfg.setdefault(attr, {})['no_summary'] = match_have[attr]['no_summary']
                                        add_cfg.setdefault(attr, {})[sub_attr] = conf[attr][sub_attr]
                                    else:
                                        add_key, del_key = {}, {}
                                        diff_keys = set(conf[attr][sub_attr].items()) ^ set(match_have[attr][sub_attr].items())
                                        for key in dict(diff_keys):
                                            if key in conf[attr][sub_attr] and key in match_have[attr][sub_attr]:
                                                add_key[key] = conf[attr][sub_attr][key]
                                                del_key[key] = match_have[attr][sub_attr][key]
                                            elif key in conf[attr][sub_attr]:
                                                add_key[key] = conf[attr][sub_attr][key]
                                            elif key in match_have[attr][sub_attr]:
                                                del_key[key] = match_have[attr][sub_attr][key]

                                        if add_key:
                                            add_key.setdefault('enabled', conf[attr][sub_attr]['enabled'])
                                            add_cfg.setdefault(attr, {})[sub_attr] = add_key
                                        if del_key:
                                            del_key.setdefault('enabled', match_have[attr][sub_attr]['enabled'])
                                            del_cfg.setdefault(attr, {})[sub_attr] = del_key

                                elif sub_attr == 'ranges':
                                    conf[attr].setdefault(sub_attr, [])
                                    match_ranges = []
                                    if attr in match_have:
                                        match_ranges = match_have[attr].get(sub_attr, [])
                                    add_range, del_range = self._get_diff_in_ranges(conf[attr][sub_attr], match_ranges)
                                    if add_range:
                                        add_cfg.setdefault(attr, {})[sub_attr] = add_range
                                    if del_range:
                                        for range_item in del_range:
                                            del_cfg.setdefault(attr, {}).setdefault(sub_attr, []).append({'prefix': range_item['prefix']})

                            for sub_attr in match_have.get(attr, {}):
                                if attr in conf:
                                    if sub_attr in conf[attr]:
                                        del_cfg.setdefault(attr, {})[sub_attr] = match_have[attr][sub_attr]

                for attr in match_have:
                    if attr not in conf:
                        del_cfg[attr] = match_have[attr]

                if add_cfg:
                    add_cfg['vrf_name'] = vrf_name
                    add_cfg['area_id'] = area_id
                    add_config.append(add_cfg)

                if del_cfg:
                    del_cfg['vrf_name'] = vrf_name
                    del_cfg['area_id'] = area_id
                    del_config.append(del_cfg)

        if state == 'overridden':
            for conf in have:
                vrf_name = conf['vrf_name']
                area_id = conf['area_id']
                want_conf = next((cmd for cmd in want if cmd['vrf_name'] == vrf_name and cmd['area_id'] == area_id), None)

                if not want_conf:
                    del_config.append({'vrf_name': conf['vrf_name'], 'area_id': conf['area_id']})

        return add_config, del_config

    def create_ospfv3_area_requests_from_commands(self, conf):
        requests = []
        payload = {}
        for area in conf:
            area_payload = {}
            inter_area_payload = {}
            vrf_name = area['vrf_name']
            area_id = area['area_id']
            for attr in area:
                if attr in ['vrf_name', 'area_id']:
                    continue
                if attr == 'nssa':
                    nssa_payload = {
                        'enable': area[attr].get('enabled'),
                        'no-summary': area[attr].get('no_summary'),
                        'default-route-metric': area[attr].get('default_originate', {}).get('metric'),
                        'default-route-metric-type': area[attr].get('default_originate', {}).get('metric_type'),
                        'default-route-originate': area[attr].get('default_originate', {}).get('enabled')
                    }
                    nssa_payload = remove_empties(nssa_payload)
                    if 'default-route-metric-type' in nssa_payload and nssa_payload['default-route-metric-type']:
                        nssa_payload['default-route-metric-type'] = "TYPE_" + str(nssa_payload['default-route-metric-type'])
                    nssa_ranges = self.update_ranges(area[attr].get('ranges', []))

                    if nssa_payload:
                        area_payload.setdefault(OSPF_KEY_EXT + attr, {})['config'] = nssa_payload

                    if nssa_ranges:
                        area_payload.setdefault(OSPF_KEY_EXT + attr, {})['ranges'] = nssa_ranges

                elif attr == 'stub':
                    stub_payload = {
                        'enable': area[attr].get('enabled'),
                        'no-summary': area[attr].get('no_summary')
                    }
                    stub_payload = remove_empties(stub_payload)
                    if stub_payload:
                        area_payload.setdefault(OSPF_KEY_EXT + attr, {})['config'] = stub_payload

                elif attr == 'ranges':
                    ranges = self.update_ranges(area[attr], 'metric')
                    if ranges:
                        inter_area_payload[attr] = ranges

                elif attr in ['filter_list_in', 'filter_list_out']:
                    if area[attr]:
                        inter_area_payload[attr.replace('_', '-')] = {
                            'config': {'name': area[attr]}
                        }

            if area_payload:
                area_payload['identifier'] = area_id
                area_payload['config'] = {
                    'identifier': area_id
                }
                payload.setdefault(vrf_name, {}).setdefault('areas', []).append(area_payload)
            elif len(area) == 2:
                area_payload['identifier'] = area_id
                area_payload['config'] = {
                    'identifier': area_id
                }
                payload.setdefault(vrf_name, {}).setdefault('areas', []).append(area_payload)

            if inter_area_payload:
                inter_area_payload['src-area'] = area_id
                inter_area_payload['config'] = {
                    'src-area': area_id
                }
                payload.setdefault(vrf_name, {}).setdefault('inter-area-policy', []).append(inter_area_payload)

        for vrf_name in payload:
            url = OSPF_URI.format(vrf_name=vrf_name)
            request_payload = {}
            if payload[vrf_name].get('areas'):
                request_payload['areas'] = {'area': payload[vrf_name]['areas']}
            if payload[vrf_name].get('inter-area-policy'):
                request_payload['global'] = {
                    'openconfig-ospfv3-ext:inter-area-propagation-policies': {
                        'inter-area-policy': payload[vrf_name]['inter-area-policy']
                    }
                }
            if request_payload:
                request_payload = {'openconfig-network-instance:ospfv3': request_payload}
                requests.append({'path': url, 'method': 'PATCH', 'data': request_payload})

        return requests

    def delete_ospfv3_area_requests_from_commands(self, conf, have):
        requests = []
        for area in conf:
            vrf_name = area['vrf_name']
            area_id = area['area_id']
            if len(area) == 2:
                match_have = next((cfg for cfg in have if cfg['vrf_name'] == vrf_name and cfg['area_id'] == area_id), None)
                if match_have:
                    for item in ['ranges', 'filter_list_in', 'filter_list_out']:
                        if item in match_have:
                            url = OSPF_URI.format(vrf_name=vrf_name) + OSPF_AREA_GLOBAL_URI.format(area_id=area_id) + "/"+ item.replace('_', '-')
                            requests.append({'path': url, 'method': 'DELETE'})
                    url = OSPF_URI.format(vrf_name=vrf_name) + OSPF_AREA_ATTRIBUTES['area_id'].format(area_id=area_id)
                    requests.append({'path': url, 'method': 'DELETE'})
                continue

            for attr in area:
                if attr in ['vrf_name', 'area_id']:
                    continue
                if attr == 'nssa' or attr == 'stub':
                    requests.extend(self.get_delete_nssa_or_stub_requests(vrf_name, area_id, area, attr))

                elif attr == 'ranges':
                    requests.extend(self.get_delete_ranges_requests(vrf_name, area_id, area[attr]))

                elif attr in ['filter_list_in', 'filter_list_out']:
                    url = OSPF_URI.format(vrf_name=vrf_name) + OSPF_AREA_ATTRIBUTES[attr].format(area_id=area_id)
                    requests.append({'path': url, 'method': 'DELETE'})

        return requests

    def get_delete_nssa_or_stub_requests(self, vrf_name, area_id, area, attr):
        requests = []
        if len(area[attr]) == 1 or ('enabled' in area[attr] and area[attr]['enabled']):
            url = OSPF_URI.format(vrf_name=vrf_name) + OSPF_AREA_ATTRIBUTES['area_id'].format(area_id=area_id)
            requests.append({'path': url + "/openconfig-ospfv3-ext:" + attr, 'method': 'DELETE'})
            return requests

        for sub_attr in area[attr]:
            if sub_attr == 'ranges':
                requests.extend(self.get_delete_ranges_requests(vrf_name, area_id, area[attr][sub_attr], attr))
            elif sub_attr == 'default_originate':
                if len(area[attr][sub_attr]) == 1 or ('enabled' in area[attr][sub_attr] and area[attr][sub_attr]['enabled']):
                    for sub_url in OSPF_AREA_ATTRIBUTES[attr][sub_attr]:
                        url = OSPF_URI.format(vrf_name=vrf_name) + sub_url.format(area_id=area_id)
                        requests.append({'path': url, 'method': 'DELETE'})
                    continue

                for default_originate_attr in area[attr][sub_attr]:
                    url = OSPF_URI.format(vrf_name=vrf_name)
                    url += OSPF_AREA_ATTRIBUTES[attr][sub_attr][default_originate_attr].format(area_id=area_id)
                    requests.append({'path': url, 'method': 'DELETE'})
            else:
                url = OSPF_URI.format(vrf_name=vrf_name)
                url += OSPF_AREA_ATTRIBUTES[attr][sub_attr].format(area_id=area_id)
                requests.append({'path': url, 'method': 'DELETE'})
        return requests

    def get_delete_ranges_requests(self, vrf_name, area_id, ranges, type=None):
        requests = []
        if type:
            base_uri = OSPF_AREA_ATTRIBUTES[type]['ranges']
        else:
            base_uri = OSPF_AREA_ATTRIBUTES['ranges']
        for range_item in ranges:
            prefix = range_item['prefix'].replace('/', '%2F')
            if len(range_item) == 1:
                url = OSPF_AREA_GLOBAL_URI + "/ranges/range={address_prefix}"
                if type:
                    url = "/areas/area={area_id}/openconfig-ospfv3-ext:nssa/ranges/range={address_prefix}"
                url = OSPF_URI.format(vrf_name=vrf_name) + url.format(area_id=area_id, address_prefix=prefix)
                requests.append({'path': url, 'method': 'DELETE'})
            else:
                if 'cost' in range_item:
                    url = OSPF_URI.format(vrf_name=vrf_name)
                    url += base_uri['cost'].format(area_id=area_id, address_prefix=prefix)
                    requests.append({'path': url, 'method': 'DELETE'})
                if 'advertise' in range_item:
                    url = OSPF_URI.format(vrf_name=vrf_name)
                    url += base_uri['advertise'].format(area_id=area_id, address_prefix=prefix)
                    requests.append({'path': url, 'method': 'DELETE'})
        return requests

    def update_ranges(self, ranges, cost_key='cost'):
        all_ranges_payload = {}
        for range_item in ranges:
            range_payload = {
                'address-prefix': range_item.get('prefix'),
                cost_key : range_item.get('cost'),
                'advertise': range_item.get('advertise')
            }
            range_payload = remove_empties(range_payload)
            if range_payload:
                range_payload = {
                    'address-prefix': range_item.get('prefix'),
                    'config': range_payload
                }
                all_ranges_payload.setdefault('range', []).append(range_payload)
        return all_ranges_payload

    def _get_diff_in_ranges(self, want_range, have_range):
        add_range, del_range = [], []
        if not want_range:
            return add_range, want_range

        if not have_range:
            return want_range, del_range

        for item in want_range:
            want_prefix = item.get('prefix')
            match_prefix = next((x for x in have_range if x.get('prefix') == want_prefix), None)
            if not match_prefix:
                add_range.append(item)
            else:
                add_cfg, del_cfg = {}, {}
                diff_keys = set(item.items()) ^ set(match_prefix.items())
                for key in dict(diff_keys):
                    if key in item and key in match_prefix:
                        add_cfg[key] = item[key]
                        del_cfg[key] = match_prefix[key]
                    elif key in item:
                        add_cfg[key] = item[key]
                    elif key in match_prefix:
                        del_cfg[key] = match_prefix[key]

                if add_cfg:
                    add_cfg['prefix'] = want_prefix
                    add_range.append(add_cfg)

                if del_cfg:
                    del_cfg['prefix'] = want_prefix
                    del_range.append(del_cfg)

        for item in have_range:
            have_prefix = item.get('prefix')
            match_prefix = next((x for x in want_range if x.get('prefix') == have_prefix), None)
            if not match_prefix:
                del_range.append(item)

        return add_range, del_range
