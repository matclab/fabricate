#!/bin/bash


CURDIR="`pwd`"

cat > umltest.inner.sh <<EOF
#!/bin/sh
(
   set -e
   set -x
   insmod /usr/lib/uml/modules/\`uname -r\`/kernel/fs/fuse/fuse.ko
   cd "$CURDIR"
   # TODO : reactivate virtualenv
   pip install  -r test-requirement.txt
   py.test -k "Fuse"
   echo Success
)
echo "\$?" > "$CURDIR"/umltest.status
halt -f
EOF

chmod +x umltest.inner.sh

/usr/bin/linux.uml mem=256M init=`pwd`/umltest.inner.sh rootfstype=hostfs rw

exit $(<umltest.status)
