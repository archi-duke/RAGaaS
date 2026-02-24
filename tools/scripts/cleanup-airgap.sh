#!/bin/bash
# Cleanup script for air-gapped package temporary files

echo "Current air-gapped package files:"
echo ""
ls -lh ragaas-airgap-* 2>/dev/null || echo "No files found"
echo ""

# Find the latest .tar.gz file
LATEST_PACKAGE=$(ls -t ragaas-airgap-*.tar.gz 2>/dev/null | head -1)

if [ -z "$LATEST_PACKAGE" ]; then
    echo "No package file found!"
    exit 1
fi

echo "Latest package: $LATEST_PACKAGE"
echo ""
echo "Temporary directories to remove:"
ls -d ragaas-airgap-*/ 2>/dev/null

read -p "Remove temporary directories? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -rf ragaas-airgap-*/
    echo "✓ Temporary directories removed"
    echo ""
    echo "Remaining:"
    ls -lh ragaas-airgap-*.tar.gz
else
    echo "Cancelled"
fi
