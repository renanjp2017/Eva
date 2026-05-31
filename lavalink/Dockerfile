FROM eclipse-temurin:21-jre-alpine

WORKDIR /lavalink

# Instala o wget para fazer o download adequado
RUN apk add --no-cache wget

# CORREÇÃO: Atualizado para a v4.2.2 (Garante compatibilidade com chamadas de voz atuais do Discord)
RUN wget https://github.com

COPY application.yml application.yml

EXPOSE 2333

ENTRYPOINT ["java", "-jar", "Lavalink.jar"]
 