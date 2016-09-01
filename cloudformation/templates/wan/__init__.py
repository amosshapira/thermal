from troposphere import Ref, Tags, GetAtt, Output, Name, cloudformation
import troposphere.ec2 as ec2
import troposphere.iam as iam
import troposphere.autoscaling as autoscaling
import troposphere.policies as policies
import troposphere.route53 as route53
import awacs.aws
import awacs.sts

import os
import yaml
import sys
import base64
import itertools
import subprocess
import pprint
import boto.vpc
import string
import datetime


def print_err(message):
    sys.stderr.write(message)


def read_yaml_file(filename):
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            return yaml.load(f) or {}

    return {}


# To extract UserData from the template:
# jq -r .Resources.Ec2NatLaunchConfiguration.Properties.UserData < json | base64 -d
def build_user_data(stack):
    user_data = '#!/bin/bash\n' + subprocess.check_output(
        'cd configuration && '
        'ln -s stacks/%(stack)s/config.yaml stack-config.yaml && '
        'shar vpcs.yaml eips.yaml stack-config.yaml && '
        'rm -f stack-config.yaml' % locals(), shell=True)
    return base64.b64encode(user_data)


def get_route_table_ids(vpc_id, region):
    conn = boto.vpc.connect_to_region(region)

    # extract route id's, filter out None results
    route_table_ids = [route_table_id for route_table_id in
                       map(lambda x: x.id,
                           conn.get_all_route_tables(filters={'vpc_id': vpc_id})) if
                       route_table_id]

    return route_table_ids


def get_vpc_id(vpc_name, region):
    conn = boto.vpc.connect_to_region(region)

    vpcs = (conn.get_all_vpcs(filters={'tag:stack-name': vpc_name}) or
            conn.get_all_vpcs(filters={'tag:aws:cloudformation:stack-name': vpc_name}))

    if vpcs:
        if len(vpcs) == 1:
            return vpcs[0].id
        else:
            print_err('%(vpc_name)s: found multiple matching VPC\'s: '
                      '%(vpcs)s\n' % locals())
            sys.exit(1)
    else:
        print_err('%(vpc_name)s: VPC not found\n' % locals())
        sys.exit(1)


def get_public_subnet_ids(vpc_id, region):
    conn = boto.vpc.connect_to_region(region)

    public_subnets = map(lambda x: x.id,
                         conn.get_all_subnets(filters={'vpc_id': vpc_id, 'tag:IsPublic': 'true'}))

    if not public_subnets:
        print_err('%(vpc_id)s: failed to find any subnets tagged IsPublic:true' %
                  locals())
        sys.exit(1)

    return public_subnets


def setup_vpn(config, template):
    stack = config['stack']
    region = config['region']
    vpc_name = config['vpc']
    public_subnets = []
    private_subnets = []
    customer_gateways = []
    nat_ec2_instances = []

    if region == None:
        print_err('%(stack)s: missing region\n' % locals())
        sys.exit(1)

    vpcs_file = read_yaml_file('configuration/vpcs.yaml')
    vpcs = vpcs_file['vpcs']
    connections = vpcs_file['connections']

    eips = read_yaml_file('configuration/eips.yaml')

    # NOTE: we look for the base VPC in 'vpcs' and in eips
    # EIP's are allocated per VPC, since it's easier to manage
    if vpc_name not in vpcs:
        print_err('%(vpc_name)s: not found in vpcs\n' % locals())
        sys.exit(1)

    if vpc_name not in eips:
        print_err(
            '%(stack)s: not found in eips; execute "scripts/manage-eips"\n' %
            locals())
        sys.exit(1)

    vpc_id = get_vpc_id(vpc_name, region)

    incoming_connections = map(
        lambda x: x.keys()[0] if isinstance(x, dict) else x,
        list(itertools.chain.from_iterable(
            x['from'] for x in connections.values()
            if 'to' in x and vpc_name in x['to'])))

    outgoing_connections = map(
        lambda x: x.keys()[0] if isinstance(x, dict) else x,
        list(itertools.chain.from_iterable(
            x['to'] for x in connections.values()
            if 'from' in x and vpc_name in x['from'])))

    # if we expect incoming VPN connections then setup a VPN gateway
    if incoming_connections:
        vpn_gateway = template.add_resource(ec2.VPNGateway(
            'VpnGateway',
            Type='ipsec.1',
            Tags=Tags(
                Name=stack,
                VPC=vpc_name,
            ),
        ))

        vpn_gateway_attachment = template.add_resource(ec2.VPCGatewayAttachment(
            'VpcGatewayAttachment',
            VpcId=vpc_id,
            VpnGatewayId=Ref(vpn_gateway),
        ))

        vpn_gateway_route_propegation = template.add_resource(ec2.VPNGatewayRoutePropagation(
            'VpnGatewayRoutePropagation',
            RouteTableIds=get_route_table_ids(vpc_id, region),
            VpnGatewayId=Ref(vpn_gateway),
            DependsOn=Name(vpn_gateway_attachment),
        ))

        for index, connection_from in enumerate(incoming_connections, 1):
            if connection_from not in vpcs:
                print_err(
                    '%(stack)s: vpn from "%(connection_from)s" not found in vpcs\n' % locals())
                sys.exit(1)

            if connection_from not in eips:
                print_err(
                    '%(stack)s: vpn from "%(connection_from)s" not found in eips\n' % locals())
                sys.exit(1)

            alphanumeric_id = ''.join([y.title()
                                       for y in connection_from.split('-')])
            customer_gateway = template.add_resource(ec2.CustomerGateway(
                alphanumeric_id + 'CGW',
                BgpAsn=vpcs[connection_from]['bgp_asn'],
                IpAddress=eips[connection_from]['public_ip'],
                Type='ipsec.1',
                Tags=Tags(
                    Name='%(connection_from)s to %(stack)s' % locals(),
                    VPC=vpc_name,
                ),
            ))

            vpn_connection = template.add_resource(ec2.VPNConnection(
                alphanumeric_id + 'VPNConnection',
                # We want this to always be 'False', for BGP
                StaticRoutesOnly=config['static_routing'],
                Type='ipsec.1',
                VpnGatewayId=Ref(vpn_gateway),
                CustomerGatewayId=Ref(customer_gateway),
                Tags=Tags(
                    Name='%s CGW: IP %s' % (
                        connection_from,
                        eips[connection_from]['public_ip']),
                    # The Tag 'RemoteVPC' is queried by
                    # configuration process on the remote VPC's NAT
                    # instance to identify the Virtual Connection they
                    # should connect to.
                    # It refers to the VPC stack name, not the WAN stack name
                    RemoteVPC=connection_from,
                    RemoteIp=eips[connection_from]['public_ip'],
                    VPC=vpc_name,
                ),
            ))

            # Add static routes to the subnets behind each incoming VPN connection
            # NOTE: Can't be used when StaticRoutesOnly is False (which is required
            # when using BGP)
            if config['static_routing']:
                vpn_connection_static_route = template.add_resource(ec2.VPNConnectionRoute(
                    '%(connection_from)s Static Route' % locals(),
                    VpnConnectionId=Ref(vpn_connection),
                    DestinationCidrBlock=vpcs[connection_from]['cidr'],
                ))

            customer_gateways.append(customer_gateway)

    else:
        vpn_gateway = None

    if outgoing_connections:
        if not region in config['nat']['ami_id']:
            print_err('AMI ID not configured for region "%(region)s"\n' %
                      locals())
            sys.exit(1)

        nat_sg = template.add_resource(ec2.SecurityGroup(
            'NatSg',
            VpcId=vpc_id,
            GroupDescription='%(stack)s router Security Group' % locals(),
            SecurityGroupEgress=[
                ec2.SecurityGroupRule(
                    CidrIp='0.0.0.0/0',
                    IpProtocol='-1',
                    FromPort='-1',
                    ToPort='-1',
                )],
            SecurityGroupIngress=  # Allow all traffic from internal networks
            map(lambda cidr:
                ec2.SecurityGroupRule(
                    CidrIp=cidr,
                    IpProtocol='-1',
                    FromPort='-1',
                    ToPort='-1'),
                ['10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16']
                ) +
            # Allow all traffic from all other locations on our WAN
            map(lambda eip:
                ec2.SecurityGroupRule(
                    CidrIp=eips[eip]['public_ip'] + '/32',
                    IpProtocol='-1',
                    FromPort='-1',
                    ToPort='-1'),
                eips.keys()
                ) +
            # Optional extra traffic sources
            map(lambda cidr:
                ec2.SecurityGroupRule(
                    CidrIp=cidr,
                    IpProtocol='-1',
                    FromPort='-1',
                    ToPort='-1'),
                config['nat']['extra_ingress_sources'] or {}
                ),
            Tags=Tags(
                Name='%(stack)s router' % locals(),
            ),
        ))

        if 'openvpn_server' in config and config['openvpn_server']:
            nat_sg.SecurityGroupIngress.append(ec2.SecurityGroupRule(
                CidrIp='0.0.0.0/0',
                IpProtocol='udp',
                FromPort='1194',
                ToPort='1194',
            ))

            if 'external_tld' in config:
                template.add_resource(route53.RecordSetType(
                    'OpenVpnDnsRecord',
                    Comment='%(stack)s OpenVPN server' % locals(),
                    HostedZoneName=config['external_tld'] + '.',
                    Name='%s.%s.' % (vpc_name, config['external_tld']),
                    ResourceRecords=[eips[vpc_name]['public_ip']],
                    TTL='900',
                    Type='A'
                ))

        assume_role_policy_statement = awacs.aws.Policy(
            Statement=[
                awacs.aws.Statement(
                    Effect=awacs.aws.Allow,
                    Principal=awacs.aws.Principal(
                        principal='Service',
                        resources=['ec2.amazonaws.com']
                    ),
                    Action=[awacs.sts.AssumeRole],
                )
            ]
        )

        root_role = template.add_resource(iam.Role(
            'RootRole',
            AssumeRolePolicyDocument=assume_role_policy_statement,
            Path='/',
        ))

        root_role_policy = template.add_resource(iam.PolicyType(
            'RootRolePolicy',
            PolicyName='AllowAllPolicy',
            PolicyDocument={
                'Version': '2012-10-17',
                'Statement': [{
                    'Action': '*',
                    'Effect': 'Allow',
                    'Resource': '*',
                }]
            },
            Roles=[Ref(root_role)],
        ))

        root_instance_profile = template.add_resource(iam.InstanceProfile(
            'RootInstanceProfile',
            Path='/',
            Roles=[Ref(root_role)],
        ))

        for index, egress_config in enumerate(config['nat']['sg_egress_rules'], 1):
            template.add_resource(ec2.SecurityGroupEgress(
                'NatSgEgressRule%d' % index,
                ToPort=egress_config['port'],
                FromPort=egress_config['port'],
                IpProtocol=egress_config['protocol'],
                CidrIp=egress_config['cidr'],
                GroupId=Ref(nat_sg),
            ))

        launch_configuration = template.add_resource(autoscaling.LaunchConfiguration(
            'Ec2NatLaunchConfiguration',
            AssociatePublicIpAddress=True,
            SecurityGroups=[Ref(nat_sg)],
            IamInstanceProfile=Ref(root_instance_profile),
            ImageId=config['nat']['ami_id'][region],
            KeyName=config['nat']['key_name'],
            InstanceType=config['nat']['instance_type'],
            UserData=build_user_data(stack),
        ))

        AutoScalingGroup = template.add_resource(autoscaling.AutoScalingGroup(
            'AutoScalingGroup',
            VPCZoneIdentifier=get_public_subnet_ids(vpc_id, region),
            TerminationPolicies=['ClosestToNextInstanceHour'],
            MinSize=1,
            MaxSize=2,
            #####
            # TODO: Have to find a way for VyOS to send the signal without
            # having access to cfn-signal script (old python version)
            # That's also the reason we allow one instance - since ha-nat
            # can't send the signal
            ####
            # CreationPolicy=policies.CreationPolicy(
            #     ResourceSignal=policies.ResourceSignal(
            #         Count=2,
            #         Timeout='PT10M',
            #     ),
            # ),
            LaunchConfigurationName=Ref(launch_configuration),
            HealthCheckType='EC2',
            UpdatePolicy=policies.UpdatePolicy(
                AutoScalingRollingUpdate=policies.AutoScalingRollingUpdate(
                    MaxBatchSize=1,
                    MinInstancesInService=1,
                    PauseTime='PT2M',
                    # TODO: switch to 'True' when we teach VyOS to send signal
                    WaitOnResourceSignals=False,
                )
            ),
            Tags=[
                autoscaling.Tag('Name', stack + ' router', True),
                autoscaling.Tag('VPC', vpc_name, True),
                # Just have to be unique for this provisioning run, could
                # be any unique string
                autoscaling.Tag('Version',
                                datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S.%f'),
                                True),
            ],
        ))
