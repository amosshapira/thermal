from troposphere import Ref, Tags, GetAtt, Output, Name, cloudformation
import troposphere.ec2 as ec2

import os
import stat
import yaml
import sys
import pprint


def read_yaml_file(filename):
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            return yaml.load(f) or {}

    return {}


def configure_vpc(config, template):
    stack = config['stack']
    region = config['region']
    public_subnets = []
    private_subnets = []

    vpcs_file = read_yaml_file('configuration/vpcs.yaml')
    vpcs = vpcs_file['vpcs']
    connections = vpcs_file['connections']
    eips = read_yaml_file('configuration/eips.yaml')

    if stack not in vpcs:
        sys.stderr.write('%s: not found in vpcs\n' % stack)
        sys.exit(1)

    if stack not in eips:
        sys.stderr.write(
            '%s: not found in eips; execute "bin/manage-eips"\n' % stack)
        sys.exit(1)

    vpc = template.add_resource(ec2.VPC(
        'VPC',
        CidrBlock=vpcs[stack]['cidr'],
        InstanceTenancy='default',
        Tags=Tags(
            Name=config['description'],
        ),
    ))

    internet_gateway = template.add_resource(ec2.InternetGateway(
        'InternetGateway',
        Tags=Tags(
            Name=config['description'],
        ),
    ))

    internet_gateway_attachment = template.add_resource(ec2.VPCGatewayAttachment(
        'InternetGatewayAttachment',
        VpcId=Ref(vpc),
        InternetGatewayId=Ref(internet_gateway),
        # DeletionPolicy='Retain',
    ))

    public_route_table = template.add_resource(ec2.RouteTable(
        'PublicRouteTable',
        VpcId=Ref(vpc),
        Tags=Tags(
            Name='%s - Public Routing Table' % stack,
        ),
    ))

    private_route_table = template.add_resource(ec2.RouteTable(
        'PrivateRouteTable',
        VpcId=Ref(vpc),
        Tags=Tags(
            Name='%s - Private Routing Table' % stack,
        ),
    ))

    # default public subnet route is through the Internet Gateway
    default_public_route = template.add_resource(ec2.Route(
        'DefaultPublicRoute',
        GatewayId=Ref(internet_gateway),
        DestinationCidrBlock='0.0.0.0/0',
        RouteTableId=Ref(public_route_table),
        DependsOn=Name(internet_gateway_attachment),
    ))

    network_acl = template.add_resource(ec2.NetworkAcl(
        'NetworkAcl',
        VpcId=Ref(vpc),
        Tags=Tags(
            Name=config['description'],
        ),
    ))

    # It's standard practice to leave Network ACL's completely permissive
    # (not to be confused with SecurityGroups)
    template.add_resource(ec2.NetworkAclEntry(
        'NetworkAclEntryIngressFromVpc',
        Protocol='-1',
        RuleNumber='100',
        CidrBlock='0.0.0.0/0',
        Egress=False,
        RuleAction='allow',
        NetworkAclId=Ref(network_acl),
    ))

    template.add_resource(ec2.NetworkAclEntry(
        'NetworkAclEntryEgress',
        Protocol='-1',
        RuleNumber='100',
        CidrBlock='0.0.0.0/0',
        Egress=True,
        RuleAction='allow',
        NetworkAclId=Ref(network_acl),
    ))

    for subnet_config in config['subnets']:
        if subnet_config['public']:
            subnet_list = public_subnets
            subnet_route_table = public_route_table
            label = 'PublicSubnet'
        else:
            subnet_list = private_subnets
            subnet_route_table = private_route_table
            label = 'PrivateSubnet'

        label += subnet_config['zone'].upper()

        subnet = template.add_resource(ec2.Subnet(
            label,
            VpcId=Ref(vpc),
            AvailabilityZone=region + subnet_config['zone'],
            CidrBlock=subnet_config['cidr'],
            Tags=Tags(
                Name='%s %s' % (config['description'], label),
                IsPublic=subnet_config['public'],
            ),
        ))

        subnet_list.append({
            'label': label,
            'object': subnet,
            'config': subnet_config,
        })

        template.add_resource(ec2.SubnetRouteTableAssociation(
            'SubnetRouteTableAssociation%s' % label,
            SubnetId=Ref(subnet),
            RouteTableId=Ref(subnet_route_table),
        ))

        template.add_resource(ec2.SubnetNetworkAclAssociation(
            'SubnetAclAssociation%s' % label,
            SubnetId=Ref(subnet),
            NetworkAclId=Ref(network_acl),
        ))

    if 'create_s3_endpoint' in config and config['create_s3_endpoint']:
        s3_endpoint = template.add_resource(ec2.VPCEndpoint(
            'S3Endpoint',
            RouteTableIds=[Ref(private_route_table)],
            PolicyDocument={
                'Version': '2012-10-17',
                'Statement': [{
                    'Action': '*',
                    'Effect': 'Allow',
                    'Resource': '*',
                    'Principal': '*'
                }]
            },
            VpcId=Ref(vpc),
            ServiceName='com.amazonaws.' + region + '.s3',
        ))
