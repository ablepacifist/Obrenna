export const cn = (...xs: (string | false | null | undefined)[]): string =>
  xs.filter(Boolean).join(' ')
