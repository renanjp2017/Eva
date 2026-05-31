FROM eclipse-temurin:17-jre-alpine

WORKDIR /lavalink

# Lavalink v4.0.8 oficial
ADD https://github.com/lavalink-devs/Lavalink/releases/download/4.0.8/Lavalink.jar Lavalink.jar

COPY application.yml application.yml

EXPOSE 2333

ENTRYPOINT ["java", "-jar", "Lavalink.jar"]