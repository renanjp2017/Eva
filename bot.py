
                            #                result_tracks = tracks.tracks if tracks and hasattr(tracks, "tracks") else []
                            print(f"[MUSIC] busca dzsearch:{query} -> {len(result_tracks)} resultado(s)")
                            if not result_tracks:
                                extra = f"[tentou tocar '{query}', não achou em lugar nenhum. Zombe do gosto musical horrível.]"
                                registrar_micro_evento(f"alguém pediu '{query}' e não existia em lugar nenhum")
                            else:
                                track = result_tracks[0]
                                if vc.playing:
                                    await vc.queue.put_wait(track)
                                    extra = f"[adicionou '{track.title}' na fila. Comente com sarcasmo que ainda vai ter que aguentar isso.]"
                                else:
                                    await vc.queue.put_wait(track)
                                    await vc.play(vc.queue.get())
                                    extra = f"[começou a tocar '{track.title}'. Reclame do gosto musical mas admita internamente que conhece.]"
                                registrar_micro_evento(f"obrigada a tocar '{track.title}'")
                        except Exception as e:
                            print(f"[LAVALINK ERR]: {e}")
                            extra = "[erro no servidor de som. Fique irritada com a tecnologia sem graça.]"

                    elif action == "skip":
                        if vc and vc.playing:
                            await vc.skip(force=True)
                            extra = "[pulou a música. Diga que era horrível mesmo.]"
                        else:
                            extra = "[pediu pra pular mas não tem nada tocando. Chame de distraído.]"

                    elif action == "stop":
                        if vc:
                            await vc.disconnect()
                            extra = "[parou tudo e saiu do canal. Expresse alívio.]"
                        else:
                            extra = "[pediu pra parar mas nem estava lá. Deboche.]"

            resposta = await gerar_resposta(message.author.id, query, extra)
            atualizar_memoria(message.author.id, texto_limpo, resposta)
            salvar_tudo()
            await message.reply(resposta)


Eva().run(DISCORD_TOKEN)