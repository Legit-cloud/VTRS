import type { Dictionary } from "./en";

/**
 * Yoruba. A first translation for review by a Yoruba speaker before the pilot: it keeps every
 * number, button and warning in plain words an agent would use, but wording and tone marks
 * should be checked by someone who writes the language daily.
 */
export const yo: Partial<Dictionary> = {
  "tab.today": "Òní",
  "tab.outbox": "Àpótí ìfiránṣẹ́",
  "tab.help": "Ìrànlọ́wọ́",

  "welcome.title": "Ṣe àkọsílẹ̀ èsì ibùdó ìdìbò rẹ",
  "welcome.body":
    "Kọ àwọn nọ́ńbà láti inú ìwé èsì, ya fọ́tò, kí o sì fi ránṣẹ́. Ó ń ṣiṣẹ́ láìsí nẹ́tíwọ́ọ̀kì, yóò sì fi ránṣẹ́ nígbà tí o bá padà sórí íńtánẹ́ẹ̀tì.",
  "welcome.signIn": "Wọlé",
  "welcome.invite": "Mo ní ìkésíni",
  "signIn.title": "Fi nọ́ńbà fóònù rẹ sílẹ̀",
  "signIn.helper": "Lo nọ́ńbà tí ẹgbẹ́ rẹ fi pè ọ́.",
  "signIn.phone": "Nọ́ńbà fóònù",
  "signIn.password": "Ọ̀rọ̀ìgbaniwọlé",
  "signIn.continue": "Tẹ̀síwájú",
  "signIn.needsNetwork":
    "Wíwọlé nílò nẹ́tíwọ́ọ̀kì. Nígbà tí o bá ti wọlé, ìṣàfilọ́lẹ̀ náà yóò ṣiṣẹ́ láìsí rẹ̀.",
  "signIn.badPhone": "Fi nọ́ńbà fóònù rẹ sílẹ̀, bíi 0803 123 4567.",
  "error.network": "A kò lè dé ibi ẹ̀rọ náà. Wo nẹ́tíwọ́ọ̀kì rẹ, kí o tún gbìyànjú.",
  "error.throttled": "Ìgbìyànjú ti pọ̀jù. Tún gbìyànjú lẹ́yìn ìṣẹ́jú {minutes}.",
  "error.device": "Fóònù yìí kọ́ ni a ṣètò àkọọ́lẹ̀ rẹ lórí rẹ̀. Béèrè ìkésíni tuntun lọ́wọ́ olùdarí rẹ.",
  "error.signIn": "A kò lè wọlé. Wo nọ́ńbà àti ọ̀rọ̀ìgbaniwọlé rẹ.",
  "error.generic": "Nǹkan kan ṣẹlẹ̀. Tún gbìyànjú.",

  "invite.title": "Ìkésíni rẹ",
  "invite.helper": "Lẹ ìjápọ̀ tí ẹgbẹ́ rẹ fi ránṣẹ́ sí ọ nínú SMS.",
  "invite.link": "Ìjápọ̀ ìkésíni",
  "invite.codeTitle": "Wo àwọn ìfiránṣẹ́ rẹ",
  "invite.codeHelper":
    "A fi kóòdù ránṣẹ́ sí {hint}. Tẹ̀ ẹ́ sí i, kí o sì yan ọ̀rọ̀ìgbaniwọlé. Fóònù yìí ni àkọọ́lẹ̀ rẹ yóò máa ṣiṣẹ́ lórí rẹ̀.",
  "invite.code": "Kóòdù",
  "invite.password": "Yan ọ̀rọ̀ìgbaniwọlé",
  "invite.passwordHelper": "Kò gbọdọ̀ dín ní àmì {min}.",
  "invite.passwordShort": "Lo àmì {min} tàbí jù bẹ́ẹ̀ lọ.",
  "invite.again": "Tún tẹ̀ ẹ́ sí i",
  "invite.mismatch": "Àwọn ọ̀rọ̀ìgbaniwọlé méjèèjì yàtọ̀.",
  "invite.create": "Ṣẹ̀dá àkọọ́lẹ̀",

  "today.title": "Òní",
  "today.noUnit": "Kò sí ibùdó ìdìbò síbẹ̀",
  "today.noUnitOnline":
    "A kò tíì yàn ọ́ sí ibùdó ìdìbò fún ìdìbò kan. Olùdarí ẹgbẹ́ rẹ ni ó ń yàn án. Fà sísàlẹ̀ láti tún wò.",
  "today.noUnitOffline":
    "Sopọ̀ lẹ́ẹ̀kan láti gba iṣẹ́ rẹ. Lẹ́yìn náà ìṣàfilọ́lẹ̀ yóò ṣiṣẹ́ láìsí nẹ́tíwọ́ọ̀kì.",
  "today.voters": "Nǹkan bí {count} olùdìbò tí a forúkọ sílẹ̀",
  "today.atUnit": "O wà ní ibùdó ìdìbò",
  "today.away": "O jìnnà sí i ní {distance}",
  "today.notOpen": "Kíkọ èsì kò tíì ṣí",
  "today.notOpenBody":
    "Ìdìbò parí ní {when}. O ṣì lè kọ àwọn nọ́ńbà; wọn yóò jáde nígbà tí ó bá ṣí.",
  "today.notOpenNoTime": "Ẹgbẹ́ rẹ yóò ṣí kíkọ èsì nígbà tí ìdìbò bá parí.",
  "today.start": "Bẹ̀rẹ̀ sí kọ èsì",
  "today.correct": "Fi àtúnṣe ránṣẹ́",
  "today.sentBack": "A dá a padà fún àtúnṣe",
  "today.approved": "A ti fọwọ́ sí i",
  "today.version": "Ẹ̀dà {n} · {when}",
  "today.updated": "A ṣe àtúnṣe iṣẹ́ rẹ {when}",

  "status.PENDING": "Ń dúró láti ránṣẹ́",
  "status.SYNCING": "Ń ránṣẹ́",
  "status.SYNCED": "A ti ránṣẹ́",
  "status.FAILED": "A kò ránṣẹ́",
  "status.REQUIRES_REVIEW": "Ó nílò àyẹ̀wò",

  "offline.banner": "O kò sí lórí íńtánẹ́ẹ̀tì. A fi àwọn èsì pamọ́ sórí fóònù yìí.",
  "offline.back": "O ti padà sórí íńtánẹ́ẹ̀tì. Ń fi {count} {noun} ránṣẹ́…",
  "noun.result": "èsì",
  "noun.results": "èsì",

  "step.votes": "Ìbò",
  "step.totals": "Àròpọ̀",
  "step.photo": "Fọ́tò",
  "step.review": "Àyẹ̀wò",
  "votes.title": "Ìbò olùdíje kọ̀ọ̀kan",
  "votes.helper":
    "Ṣẹ̀dà nọ́ńbà tí ó wà lẹ́gbẹ̀ẹ́ orúkọ kọ̀ọ̀kan láti inú ìwé èsì. Kọ 0 bí olùdíje kò bá ní ìbò.",
  "votes.label": "Ìbò",
  "totals.title": "Àròpọ̀ láti inú ìwé",
  "totals.helper": "Àwọn wọ̀nyí ni àròpọ̀ tí a tẹ̀ sí ìsàlẹ̀ ìwé náà.",
  "totals.ok": "Ìbò àwọn olùdíje {sum} = Ìbò tó péye {valid} ✓",
  "totals.stillSend": "Bí ìwé náà bá sọ bẹ́ẹ̀ ní tòótọ́, o ṣì lè fi ránṣẹ́. Olùdarí kan yóò yẹ̀ ẹ́ wò.",
  "field.accredited": "Àwọn olùdìbò tí a fọwọ́ sí",
  "field.valid": "Ìbò tó péye",
  "field.rejected": "Ìbò tí a kọ̀",
  "field.total_cast": "Gbogbo ìbò tí a dì",
  "check.candidates":
    "Ìbò àwọn olùdíje jẹ́ {sum}, ṣùgbọ́n ìbò tó péye jẹ́ {valid}. Yẹ ìwé èsì náà wò.",
  "check.rejected":
    "Ìbò tó péye ({valid}) àti ìbò tí a kọ̀ ({rejected}) jẹ́ {sum}, ṣùgbọ́n gbogbo ìbò tí a dì jẹ́ {cast}. Yẹ ìwé èsì náà wò.",
  "check.accredited":
    "A dì ìbò {cast}, ṣùgbọ́n àwọn olùdìbò {accredited} nìkan ni a fọwọ́ sí. Yẹ ìwé èsì náà wò.",
  "common.next": "Tẹ̀síwájú",
  "photo.allowTitle": "Gba kámẹ́rà láàyè",
  "photo.allowBody":
    "A máa lo kámẹ́rà láti ya fọ́tò ìwé èsì nìkan. Fọ́tò náà yóò lọ sí ẹgbẹ́ rẹ pẹ̀lú àwọn nọ́ńbà, kí wọ́n lè yẹ̀ wọ́n wò.",
  "photo.allow": "Gba kámẹ́rà láàyè",
  "photo.settings": "Ṣí àwọn ètò",
  "photo.readableTitle": "Ṣé a lè ka ìwé náà?",
  "photo.readableBody":
    "Rí i dájú pé a lè ka gbogbo nọ́ńbà, lẹ́yìn náà lo fọ́tò náà. Tún ya á bí ìmọ́lẹ̀ bá ń dà, òjìji wà, tàbí a gé e.",
  "photo.use": "Lo fọ́tò yìí",
  "photo.retake": "Tún ya",
  "photo.tips": "Kún férémù náà · Kò gbọdọ̀ sí òjìji",
  "photo.take": "Ya fọ́tò",
  "photo.tooLarge": "Fọ́tò náà tóbi jù láti fi ránṣẹ́. Sún mọ́ ìwé náà kí o sì tún gbìyànjú.",
  "review.title": "Yẹ̀ ẹ́ wò, lẹ́yìn náà fi ránṣẹ́",
  "review.helper":
    "Lẹ́yìn tí a bá ti fi ránṣẹ́, a kò lè yí èsì padà. A máa ń ṣe àtúnṣe àṣìṣe nípa fífi àtúnṣe ránṣẹ́.",
  "review.send": "Fi èsì ránṣẹ́",
  "review.officerLook": "Èyí yóò lọ sọ́dọ̀ olùdarí fún àyẹ̀wò",
  "review.photo": "Fọ́tò ìwé èsì",
  "review.location": "Ibùdó",
  "review.locationOn":
    "A máa kọ ibi tí o wà sílẹ̀ lẹ́ẹ̀kan, nígbà tí o bá fi ránṣẹ́, láti jẹ́rìí pé o wà ní ibùdó ìdìbò.",
  "review.locationAsk":
    "A máa lo ibi tí o wà lẹ́ẹ̀kan, nígbà tí o bá fi èsì ránṣẹ́, láti jẹ́rìí pé o wà ní ibùdó ìdìbò rẹ. A kì í tọpa ọ́.",
  "review.allowLocation": "Gba ibùdó láàyè",
  "review.saveFailed": "A kò lè fi èsì náà pamọ́. Tún gbìyànjú.",

  "done.sent": "A ti fi èsì ránṣẹ́",
  "done.sentBody": "Ẹgbẹ́ rẹ lè rí {ward}, {unit} báyìí.",
  "done.saved": "A ti fi pamọ́ sórí fóònù yìí",
  "done.savedBody": "A óò fi ránṣẹ́ ní kété tí o bá ní nẹ́tíwọ́ọ̀kì. O lè ti ìṣàfilọ́lẹ̀ náà.",
  "done.review": "A ti ránṣẹ́, ó nílò àyẹ̀wò",
  "done.reviewBody": "Olùdarí kan yóò yẹ nǹkan kan wò. O kò nílò láti ṣe ohunkóhun.",
  "done.failed": "A kò tíì ránṣẹ́",
  "done.failedBody": "Èsì rẹ wà ní ààbò lórí fóònù yìí. Wo nẹ́tíwọ́ọ̀kì rẹ kí o sì tún gbìyànjú.",
  "done.photoSending": "Fọ́tò náà ṣì ń lọ.",
  "done.tryAgain": "Tún gbìyànjú",
  "done.goToday": "Lọ sí Òní",

  "outbox.title": "Àpótí ìfiránṣẹ́",
  "outbox.sendAll": "Fi gbogbo rẹ̀ ránṣẹ́",
  "outbox.tryAgain": "Tún gbìyànjú",
  "outbox.emptyTitle": "Kò sí ohun tí a tíì fi ránṣẹ́",
  "outbox.emptyBody":
    "Àwọn èsì tí o bá kọ yóò hàn níbí pẹ̀lú ipò wọn. Fà sísàlẹ̀ láti wo ìmúdójúìwọ̀n.",
  "outbox.photoSent": "A ti fi fọ́tò ránṣẹ́",
  "outbox.photoFailed": "A kò fi fọ́tò ránṣẹ́. Tẹ Tún gbìyànjú.",
  "outbox.photoSending": "Fọ́tò náà ṣì ń lọ",
  "outbox.photoWaits": "Fọ́tò náà ń dúró pẹ̀lú èsì",
  "outbox.officer": "Olùdarí kan yóò yẹ nǹkan kan wò. O kò nílò láti ṣe ohunkóhun.",
  "outbox.recorded": "A kọ ọ́ {when}",
  "outbox.sentWhen": " · a fi ránṣẹ́ {when}",
  "outbox.versionNo": " · ẹ̀dà {n}",
  "outbox.retryLine":
    "A kò fi èsì ránṣẹ́. Wo nẹ́tíwọ́ọ̀kì rẹ, lẹ́yìn náà tẹ Tún gbìyànjú. Èsì rẹ wà ní ààbò lórí fóònù yìí.",

  "help.title": "Ìrànlọ́wọ́",
  "help.call": "Pe ìrànlọ́wọ́",
  "help.whatsapp": "Fi ìfiránṣẹ́ ránṣẹ́ lórí WhatsApp",
  "help.noSupport":
    "Olùdarí ẹgbẹ́ rẹ ni ẹni àkọ́kọ́ tí o lè kàn sí. Àwọn nọ́ńbà ìrànlọ́wọ́ yóò hàn níbí nígbà tí ẹgbẹ́ rẹ bá fi wọ́n sílẹ̀.",
  "help.language": "Èdè",
  "help.signedInAs": "O ti wọlé gẹ́gẹ́ bí {name}",
  "help.signOut": "Jáde",
  "help.signOutTitle": "Jáde?",
  "help.signOutPending":
    "{count} {noun} ṣì wà lórí fóònù yìí tí a kò tíì fi ránṣẹ́. Jáde lẹ́yìn tí a bá ti fi wọ́n ránṣẹ́, bí kò bá ṣe bẹ́ẹ̀ wọn yóò dúró títí o fi tún wọlé.",
  "help.signOutPlain": "Wàá nílò ọ̀rọ̀ìgbaniwọlé rẹ láti tún wọlé.",
  "help.stay": "Dúró nínú ìwọlé",
  "help.g1.title": "Ṣíṣiṣẹ́ láìsí nẹ́tíwọ́ọ̀kì",
  "help.g1.body":
    "O lè kọ èsì kí o sì ya fọ́tò láìsí nẹ́tíwọ́ọ̀kì rárá. Èsì náà yóò dúró lórí fóònù rẹ, tí a fi àmì Ń dúró láti ránṣẹ́ sí, yóò sì jáde fúnra rẹ̀ nígbà tí o bá ní ìsopọ̀. O lè ti ìṣàfilọ́lẹ̀ náà.",
  "help.g2.title": "Yíya fọ́tò ìwé tó dára",
  "help.g2.body":
    "Kún férémù náà pẹ̀lú gbogbo ìwé náà. Dúró ní ibi tí ìmọ́lẹ̀ dára, láìsí òjìji lórí rẹ̀. Mú fóònù náà dúró ṣinṣin, lẹ́yìn náà rí i dájú pé a lè ka àwọn nọ́ńbà kí o tó lo fọ́tò náà.",
  "help.g3.title": "Bí àwọn nọ́ńbà kò bá tó ara wọn",
  "help.g3.body":
    "Ìṣàfilọ́lẹ̀ náà yóò sọ fún ọ nígbà tí ìbò àwọn olùdíje kò bá dọ́gba pẹ̀lú ìbò tó péye, tàbí tí ìbò tí a dì bá ju àwọn olùdìbò tí a fọwọ́ sí lọ. Wo ìwé náà. Bí ó bá sọ bẹ́ẹ̀ ní tòótọ́, o ṣì lè fi ránṣẹ́. Olùdarí kan yóò yẹ̀ ẹ́ wò.",
  "help.g4.title": "Bí o bá ṣàṣìṣe lẹ́yìn tí o ti ránṣẹ́",
  "help.g4.body":
    "A kò lè ṣàtúnṣe èsì tí a ti ránṣẹ́. Ṣí Òní kí o sì yan Fi àtúnṣe ránṣẹ́. Olùdarí rẹ yóò rí ẹ̀dà méjèèjì.",
};
