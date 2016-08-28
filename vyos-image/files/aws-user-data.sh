#!/bin/bash
exec > >(tee /root/log.txt)
exec 2>&1

set -x
set -e

# This will cause Packer ssh only succeed after the reboot
sed -i -e 's/^Port 22$/Port 122/' /etc/ssh/sshd_config

parted --script /dev/xvdf mklabel msdos
parted --script --align optimal /dev/xvdf mkpart primary 0% 100%
mkfs.ext4 -L cloudimg-rootfs /dev/xvdf1
parted --script /dev/xvdf set 1 boot
e2label /dev/xvda1 ""

mkdir -p /tmp/root
mount /dev/xvdf1 /tmp/root
cp -ax / /tmp/root
rm -rf /tmp/root/dev
cp -ax /dev /tmp/root/dev

echo "GRUB_DEVICE=LABEL=cloudimg-rootfs
GRUB_DISABLE_LINUX_UUID=true
GRUB_DISABLE_OS_PROBER=true" >> /etc/default/grub
grub-mkconfig -o /boot/grub/grub.cfg
cp -avb /boot/grub/grub.cfg /tmp/root/boot/grub/grub.cfg

exec reboot

exit 1
