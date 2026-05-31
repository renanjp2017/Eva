FROM eclipse-temurin:17-jre-alpine

WORKDIR /lavalink

# Baixa o Lavalink jar
ADD https://github.com/lavalink-devtools/youtube-source/releases/download/v1.11.3/Lavalink.jar Lavalink.jar

COPY application.yml application.yml

EXPOSE 2333

ENTRYPOINT ["java", "-jar", "Lavalink.jar"]