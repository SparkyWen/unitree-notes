// Transcription prompt. Passed to OpenAI Realtime as the
// `audio.input.transcription.prompt` to bias the ASR towards medical
// vocabulary and to discourage rewriting.

export const TRANSCRIPTION_PROMPT = `This is a doctor-visit or follow-up conversation between a doctor, patient, and possibly a family member.
Transcribe accurately.
Do not summarize.
Do not rewrite.
Preserve medication names, test names, symptoms, dosage, frequency, duration, timing, follow-up dates, allergies, medical history, and mixed Chinese-English phrases.
Possible terms include medication, antibiotics, ibuprofen, paracetamol, blood test, CT, MRI, follow-up, dosage, once daily, after meals, before meals, allergy, fever, cough, pain, review, referral.
`;
