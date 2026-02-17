#!/usr/bin/env bash

# Update packages
apt-get update

# Install ODBC dependencies
apt-get install -y curl apt-transport-https gnupg2 unixodbc unixodbc-dev

# Add Microsoft repo
curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add -

curl https://packages.microsoft.com/config/ubuntu/20.04/prod.list > /etc/apt/sources.list.d/mssql-release.list

apt-get update

# Install SQL Server ODBC Driver
ACCEPT_EULA=Y apt-get install -y msodbcsql17
