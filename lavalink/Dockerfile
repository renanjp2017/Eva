FROM eclipse-temurin:17-jre-alpine

WORKDIR /lavalink

# CORREÇÃO: Baixa o Lavalink v4 oficial do repositório correto
ADD https://github.com/lavalink-devs/Lavalink/releases/download/4.0.8/Lavalink.jar Lavalink.jar

COPY application.yml application.yml

EXPOSE 2333

ENTRYPOINT ["java", "-jar", "Lavalink.jar"]
