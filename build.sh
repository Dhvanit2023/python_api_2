#!/usr/bin/env bash

apt-get update

apt-get install -y curl gnupg

curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add -

curl https://packages.microsoft.com/config/ubuntu/22.04/prod.list > /etc/apt/sources.list.d/mssql-release.list

apt-get update

ACCEPT_EULA=Y apt-get install -y msodbcsql17 unixodbc-dev
