/**
 * Every word the agent reads, in one place. English is the source: add a key here first, then
 * give it a Yoruba string in yo.ts (a missing one falls back to English, never to a blank).
 * `{name}` marks a value filled in at run time.
 */
export const en = {
  // tabs
  "tab.today": "Today",
  "tab.outbox": "Outbox",
  "tab.help": "Help",

  // welcome and sign-in
  "welcome.title": "Record your polling unit's result",
  "welcome.body":
    "Enter the numbers from the result sheet, take a photo, and send. It works without a network and sends when you are back online.",
  "welcome.signIn": "Sign in",
  "welcome.invite": "I have an invitation",
  "signIn.title": "Enter your mobile number",
  "signIn.helper": "Use the number your party invited you with.",
  "signIn.phone": "Phone number",
  "signIn.password": "Password",
  "signIn.continue": "Continue",
  "signIn.needsNetwork": "Signing in needs a network. Once you are in, the app works without one.",
  "signIn.badPhone": "Enter your phone number, like 0803 123 4567.",
  "error.network": "Could not reach the server. Check your network and try again.",
  "error.throttled": "Too many attempts. Try again in {minutes} min.",
  "error.device":
    "This phone is not the one your account was set up on. Ask your officer for a new invitation.",
  "error.signIn": "Could not sign in. Check your number and password.",
  "error.generic": "Something went wrong. Try again.",

  // invitation
  "invite.title": "Your invitation",
  "invite.helper": "Paste the link from the SMS your party sent you.",
  "invite.link": "Invitation link",
  "invite.codeTitle": "Check your messages",
  "invite.codeHelper":
    "We sent a code to {hint}. Enter it and choose a password. This phone becomes the one your account works on.",
  "invite.code": "Code",
  "invite.password": "Choose a password",
  "invite.passwordHelper": "At least {min} characters.",
  "invite.passwordShort": "Use at least {min} characters.",
  "invite.again": "Type it again",
  "invite.mismatch": "The two passwords are different.",
  "invite.create": "Create account",

  // today
  "today.title": "Today",
  "today.noUnit": "No polling unit yet",
  "today.noUnitOnline":
    "You have not been placed at a polling unit for an election. Your party officer assigns this. Pull down to check again.",
  "today.noUnitOffline":
    "Connect once to download your assignment. After that the app works without a network.",
  "today.voters": "About {count} registered voters",
  "today.atUnit": "You're at the polling unit",
  "today.away": "{distance} away",
  "today.notOpen": "Result entry is not open yet",
  "today.notOpenBody":
    "Polls close {when}. You can still fill in the numbers; they send when capture opens.",
  "today.notOpenNoTime": "Your party opens result entry when polls close.",
  "today.start": "Start result entry",
  "today.correct": "Send a correction",
  "today.sentBack": "Sent back for correction",
  "today.approved": "Approved",
  "today.version": "Version {n} · {when}",
  "today.updated": "Assignment updated {when}",

  // status
  "status.PENDING": "Waiting to send",
  "status.SYNCING": "Sending",
  "status.SYNCED": "Sent",
  "status.FAILED": "Not sent",
  "status.REQUIRES_REVIEW": "Needs review",

  // offline banner
  "offline.banner": "You're offline. Results are saved on this phone.",
  "offline.back": "Back online. Sending {count} {noun}…",
  "noun.result": "result",
  "noun.results": "results",

  // capture
  "step.votes": "Votes",
  "step.totals": "Totals",
  "step.photo": "Photo",
  "step.review": "Review",
  "votes.title": "Votes for each candidate",
  "votes.helper":
    "Copy the number beside each name from the result sheet. Write 0 if a candidate has none.",
  "votes.label": "Votes",
  "totals.title": "Totals from the sheet",
  "totals.helper": "These are the totals printed at the bottom of the sheet.",
  "totals.ok": "Candidate votes {sum} = Valid votes {valid} ✓",
  "totals.stillSend":
    "If the sheet really says this, you can still send it. An officer will look at it.",
  "field.accredited": "Accredited voters",
  "field.valid": "Valid votes",
  "field.rejected": "Rejected ballots",
  "field.total_cast": "Total votes cast",
  "check.candidates":
    "Candidate votes add up to {sum}, but valid votes is {valid}. Check the result sheet.",
  "check.rejected":
    "Valid votes ({valid}) plus rejected ({rejected}) is {sum}, but total cast is {cast}. Check the result sheet.",
  "check.accredited":
    "{cast} votes were cast, but only {accredited} voters were accredited. Check the result sheet.",
  "common.next": "Next",
  "photo.allowTitle": "Allow the camera",
  "photo.allowBody":
    "The camera is used only to photograph the result sheet. The photo goes to your party with the numbers, so they can check them.",
  "photo.allow": "Allow camera",
  "photo.settings": "Open settings",
  "photo.readableTitle": "Is the sheet readable?",
  "photo.readableBody":
    "Check every number can be read, then use the photo. Retake it if there is glare, a shadow, or it is cut off.",
  "photo.use": "Use photo",
  "photo.retake": "Retake",
  "photo.tips": "Fill the frame · No shadows",
  "photo.take": "Take photo",
  "photo.tooLarge": "The photo is too large to send. Move closer to the sheet and try again.",
  "review.title": "Check, then send",
  "review.helper":
    "Once sent, a result cannot be edited. A mistake is fixed by sending a correction.",
  "review.send": "Send result",
  "review.officerLook": "This will go to an officer for a look",
  "review.photo": "Result sheet photo",
  "review.location": "Location",
  "review.locationOn":
    "Your position is recorded once, when you send, to confirm you are at the polling unit.",
  "review.locationAsk":
    "We use your location once, when you send a result, to confirm you're at your polling unit. We don't track you.",
  "review.allowLocation": "Allow location",
  "review.saveFailed": "Could not save the result. Try again.",

  // confirmation
  "done.sent": "Result sent",
  "done.sentBody": "Your party can now see {ward}, {unit}.",
  "done.saved": "Saved on this phone",
  "done.savedBody": "We'll send it as soon as you have a network. You can close the app.",
  "done.review": "Sent, needs review",
  "done.reviewBody": "An officer will check one thing. You don't need to do anything.",
  "done.failed": "Not sent yet",
  "done.failedBody": "Your result is safe on this phone. Check your network and try again.",
  "done.photoSending": "The photo is still sending.",
  "done.tryAgain": "Try again",
  "done.goToday": "Go to Today",

  // outbox
  "outbox.title": "Outbox",
  "outbox.sendAll": "Send all",
  "outbox.tryAgain": "Try again",
  "outbox.emptyTitle": "Nothing sent yet",
  "outbox.emptyBody":
    "Results you record appear here with their status. Pull down to check for updates.",
  "outbox.photoSent": "Photo sent",
  "outbox.photoFailed": "Photo not sent. Tap Try again.",
  "outbox.photoSending": "Photo is still sending",
  "outbox.photoWaits": "Photo waits with the result",
  "outbox.officer": "An officer will check one thing. You do not need to do anything.",
  "outbox.recorded": "Recorded {when}",
  "outbox.sentWhen": " · sent {when}",
  "outbox.versionNo": " · version {n}",
  "outbox.retryLine":
    "Result not sent. Check your network, then tap Try again. Your result is safe on this phone.",

  // help
  "help.title": "Help",
  "help.call": "Call support",
  "help.whatsapp": "Message on WhatsApp",
  "help.noSupport":
    "Your party officer is your first point of contact. Support numbers appear here when your party sets them.",
  "help.language": "Language",
  "help.signedInAs": "Signed in as {name}",
  "help.signOut": "Sign out",
  "help.signOutTitle": "Sign out?",
  "help.signOutPending":
    "{count} {noun} still on this phone and not sent. Sign out only after they are sent, or they will wait until you sign in again.",
  "help.signOutPlain": "You will need your password to sign in again.",
  "help.stay": "Stay signed in",
  "help.g1.title": "Working without a network",
  "help.g1.body":
    "You can enter results and take the photo with no network at all. The result waits on your phone, marked Waiting to send, and goes by itself when you have a signal. You can close the app.",
  "help.g2.title": "Taking a good photo of the sheet",
  "help.g2.body":
    "Fill the frame with the whole sheet. Stand in good light with no shadow across it. Keep the phone flat and still, then check the numbers are readable before you use the photo.",
  "help.g3.title": "If the numbers do not add up",
  "help.g3.body":
    "The app tells you when the candidates' votes do not equal the valid votes, or more votes were cast than voters accredited. Check the sheet. If it really says that, you can still send it. An officer will look at it.",
  "help.g4.title": "If you made a mistake after sending",
  "help.g4.body":
    "A sent result cannot be edited. Open Today and choose Send a correction. Your officer sees both versions.",
} as const;

export type Key = keyof typeof en;
export type Dictionary = Record<Key, string>;
