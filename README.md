# Thermal: VyOS based VPC WAN
Setup wide-area-network using IPSec tunnels between multiple AWS VPC's

Requirements:

1. [Packer](packer.io) - to build the VyOS AMI's
2. [AWS CLI](https://aws.amazon.com/cli/), configured with an API key and secret.
3. Python packages:
  1. [boto](https://github.com/boto/boto) - for now we use Boto 2, not 3.
  2. [Troposphere](https://github.com/cloudtools/troposphere) - to build CloudFormation stacks with Python
4. Existing AWS account:
  1. VPC in `us-east-1` to run the AMI building in (if you want to try this code as-is)
  2. Configured API credentials under your `~/.aws`

To try the repo:

```
$ git clone https://github.com/amosshapira/thermal.git
$ cd thermal/vyos-images

# Pick a VPC and subnet in us-east-1 (Virginia) to execute the AMI building
# The instance will come up with a public network interface, so the subnet has to
# support this.
# build AMI's
$ VPC_ID=vpc-XXXXXXXX SUBNET_ID=subnet-YYYYYYYY ./run-packer

# Note the last lines of the output, they contain the AMI id's for the next step
$ cd ../cloudformation
$ vim configuration/templates/wan/config.yaml

# edit to update the AMI's ID's from the output of "run-packer".
# also add your ssh key name to "key_name"
```
Now bring up the entire setup:

```
$ ./bin/demo-up-all-examples
```
This should bring up the VPC's in multiple AWS regions and the Wide Area Network (WAN) connecting all the VPC's.

It takes a couple of minutes for each VPN connection to be fully up and routes propagated. Have patience my young Padawan.

The output of the above command "tails" the CloudFormation events for each stack as it is being created. Normal output is in Green. If there is a failed event then it will appear in Red then all following events will switch to Purple.

When the script is done you can check the status of the stacks by executing `./bin/manage-cfn list`:

```
$ ./bin/manage-cfn list
8 stacks: ........

Name              Profile    Region     State    Status           Created              Last Updated    Description
----------------  ---------  ---------  -------  ---------------  -------------------  --------------  -------------
ohio              default    us-east-2  up       CREATE_COMPLETE  2017-01-02 01:41:03                  Ohio VPC
ohio-wan          default    us-east-2  up       CREATE_COMPLETE  2017-01-02 01:42:21                  Ohio WAN
oregon            default    us-west-2  up       CREATE_COMPLETE  2017-01-02 01:45:56                  Oregon VPC
oregon-wan        default    us-west-2  up       CREATE_COMPLETE  2017-01-02 01:47:09                  Oregon WAN
virginia          default    us-east-1  up       CREATE_COMPLETE  2017-01-02 01:36:09                  Virginia
virginia-hub      default    us-east-1  up       CREATE_COMPLETE  2017-01-02 01:26:17                  Virginia Hub
virginia-hub-wan  default    us-east-1  up       CREATE_COMPLETE  2017-01-02 01:27:33                  Virginia Hub WAN
virginia-wan      default    us-east-1  up       CREATE_COMPLETE  2017-01-02 01:37:27                  Virginia WAN
```

There are more useful sub-command, execute `manage-cfn --help` for details:

```
$ ./bin/manage-cfn --help
Usage:
manage-cfn up --stack stack [--tail] [--debug] [--force] [--color]
manage-cfn provision --stack stack [--tail] [--debug] [--force] [--color]
manage-cfn diff --stack stack [--debug]
manage-cfn down --stack stack [--tail] [--debug] [--force] [--no-color]
manage-cfn show --stack stack [--debug]
manage-cfn status --stack stack [--debug]
manage-cfn tail --stack stack [--debug] [--color]
manage-cfn verify --stack stack [--debug] [--color]
manage-cfn print [--stack stack] [--yaml | --json | --raw] [KEY...]
manage-cfn list [--debug]

Arguments:
  KEY                       optional one or more keys to print

Options:
  -h --help                 Show this help text
  --color                   Force color output (default if console output)
  -d --debug                Turn on debug logging
  -f --force                Skip prompting for confirmation
                              (default if no console input)
  -j --json                 Print in JSON format (default)
  -r --raw                  Print raw strings
  -s stack --stack=stack    Stack to operate on
  --tail                    Force tail stack events (default if console output)
  -y --yaml                 Print in YAML format
```

When the links are up and the routes come through, the routing table of the private network in the hub will look something like this:
![](https://github.com/amosshapira/thermal/raw/master/docs/images/route-tables.png)

You can see that the routes from all remote VPC's are available and were propagated automatically (the "Yes" value under the "Propagated" column).

When a tunnel is up, you'll see in the VPN Connection "UP" in the hub:
![](https://github.com/amosshapira/thermal/raw/master/docs/images/tunnels-up.png)

The "Details" column shows the number of routes advertised by that spoke (2 in this case - one for each subnet). And the "Status" of "UP" indicates that the BGP-4 session is fine.

The auto-generated security groups automatically open up full access from each location to the others, to ease troubleshooting. But this means that you won't be able to ssh into the VyOS EC2 instances from your laptop to examine them.

To allow that, you have to edit the security group of one of the VyOS instances and add an SSH rule with "My IP", like this:
![](https://github.com/amosshapira/thermal/raw/master/docs/images/adding-my-ip-ssh.png)

Once this is in place, you can ssh to user "`vyos`" on that elastic IP address using the ssh key you specified.

Once you finished with the test, you can take down the entire setup by typing:

```
$ ./bin/demo-down-all-examples
```

This will still leave behind the allocated Elastic IP's. You'll have to delete them yourself to avoid charges by AWS.
