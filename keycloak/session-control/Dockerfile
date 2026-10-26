FROM maven:3.9.11-eclipse-temurin-21@sha256:6fdc855a6ed81d288ca7ca37ac6ff5e9308b612485c0801d70b25a858c83d237 AS build
WORKDIR /build
COPY keycloak/session-control/pom.xml ./pom.xml
COPY keycloak/session-control/src ./src
RUN --mount=type=cache,id=rac-keycloak-maven,target=/root/.m2 mvn -B -ntp package

FROM quay.io/keycloak/keycloak:26.8.1@sha256:79c623a22abacf3fe6c00a5fb30f5b7843d717b234033b80995891c06116d244
COPY --from=build --chown=1000:0 /build/target/rac-session-control-1.0.0.jar /opt/keycloak/providers/rac-session-control.jar
RUN /opt/keycloak/bin/kc.sh build --db=postgres --health-enabled=true
