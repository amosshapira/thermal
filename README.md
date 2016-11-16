# Thermal: VyOS based VPC WAN
Setup wide-area-network using IPSec tunnels between multiple AWS VPC's

Requirements:

1. [Packer](packer.io) - to build the VyOS AMI's
2. [AWS CLI](https://aws.amazon.com/cli/), configured with an API key and secret.
3. Python packages:
  1. [boto](https://github.com/boto/boto) - for now we use Boto 2, not 3.
  2. [Troposphere](https://github.com/cloudtools/troposphere) - to build CloudFormation stacks with Python

To try the repo:

```
$ git clone https://github.com/amosshapira/thermal.git
$ cd thermal/vyos-images
# build AMI's
$ ./run-packer
$ cd ../cloudformation
$ vim configuration/templates/wan/config.yaml
# edit to update the AMI's ID's as printed by Packer.
# also add your ssh key name to "key_name"
```

```
$ ./bin/demo-up-all-examples
```
This should bring up the entire WAN and connect between all VPC's.

It takes a couple of minutes for each VPN connection to be fully up and routes propagted. Have patience.

When the links are up and the routes come through, the routing table of the private network in the hub will look something like this:
![](https://github.com/amosshapira/thermal/raw/master/docs/images/route-tables.png)

You can see that the routes from all remote VPC's are available and were propagted automatically.

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

This will still leave behind the allocated Elastic IP's. You'll have to delete them yourself to avoid paying for them.
