# Local learning controller. Docker socket access is explained in the guide.
FROM docker:29.7.2-cli AS docker_cli
FROM jenkins/jenkins:2.580.1-jdk21
USER root
COPY --from=docker_cli /usr/local/bin/docker /usr/local/bin/docker
COPY plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli --plugin-file /usr/share/jenkins/ref/plugins.txt
USER jenkins
