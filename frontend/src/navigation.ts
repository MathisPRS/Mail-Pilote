/** Navigation hors de l'appli (page de connexion Google / Microsoft) ; remplaçable en test. */
export const nav = {
  assign(url: string) {
    window.location.assign(url);
  },
};
