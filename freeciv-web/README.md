Freeciv 3D web application 
=======================

This is the Freeciv 3D web application, which consists of the Java servlets 
and filters for running the web client, JSP templates, javascript code
and other web content. 

Derived Sources
===============

Freeciv-web uses packet definitions, tilesets, and other resources
derived from the original freeciv project, keeping these up to date by
generating them during install from freeciv source.

Scripts to generate these files are in `$freeciv-web/scripts` and they
are generated to `$freeciv-web/freeciv-web/src/derived`. See the
README.md in those directories for more info.

Tomcat + nginx setup
================================
Freeciv-web supports the Tomcat  application server for hosting the Java web application.

The build scripts are updated to build Freeciv-web for Tomcat by default,
so setting up Freeciv-web with Vagrant will configure this automatically.
Also see the suggested nginx.conf file in publite2/nginx.conf

  https://tomcat.apache.org/  
  http://nginx.org/  

Build script
============
Use maven to build and deploy, by running this build script: 
sh build.sh

There is also a build-js.sh script to build just JavaScript quickly for development work.

The build script will also create a data webapp directory where savegames and scorelogs are stored.

Flyway migrations of the database are supported. The repository provides a configuration template and a generator to create `freeciv-web/flyway.properties`:

1. Copy the example config into place (if you don't already have `config/config`):

```bash
cp config/config.dist config/config
```

1. Edit `config/config` and set your DB variables (`DB_USER`, `DB_PASSWORD`, `DB_NAME`, and any other required values).

1. Run the template generator to produce configuration files from the templates (this will create `freeciv-web/flyway.properties` from `config/flyway.tmpl`):

```bash
./config/gen-from-templates.sh config/config
```

1. Confirm `freeciv-web/flyway.properties` exists and contains your DB settings. Note: `freeciv-web/flyway.properties` is ignored by git (`freeciv-web/.gitignore`).
To migrate the database to the latest version, run this Maven command:
mvn flyway:migrate


Copyright (C) 2007-2024 Andreas Røsdal. 
Released under the GNU AFFERO GENERAL PUBLIC LICENSE.

Source code, 3D models and all files part of Freeciv 3D / FCIV.NET are covered by the GNU AFFERO GENERAL PUBLIC LICENSE.
See LICENSE.txt for the AGPL license of Freeciv 3D / FCIV.NET. This license means that these 3D models
are free and open source, and that any modifications and redistributions must also be
free and open source, with the AGPL license.
