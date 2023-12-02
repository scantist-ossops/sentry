import {useEffect, useMemo, useState} from 'react';
import * as Sentry from '@sentry/react';
import * as Prism from 'prismjs';

import {loadPrismLanguage, prismLanguageMap} from 'sentry/utils/prism';

type PrismHighlightParams = {
  code: string;
  language: string;
};

export type SyntaxHighlightToken = {
  children: string;
  className: string;
};

export type SyntaxHighlightLine = SyntaxHighlightToken[];

type IntermediateToken = {
  children: string;
  types: Set<string>;
};

const useLoadPrismLanguage = (language: string, {onLoad}: {onLoad: () => void}) => {
  useEffect(() => {
    if (!language) {
      return;
    }

    loadPrismLanguage(language, {
      onLoad,
      onError: () => {
        Sentry.captureException(
          new Error('Prism.js failed to load language for stack trace'),
          {extra: {language}}
        );
      },
    });
  }, [language, onLoad]);
};

const getPrismGrammar = (language: string) => {
  const fullLanguage = prismLanguageMap[language];
  return Prism.languages[fullLanguage] ?? null;
};

const splitMultipleTokensByLine = (
  tokens: Array<string | Prism.Token>,
  types: Set<string> = new Set(['token'])
) => {
  const lines: IntermediateToken[][] = [];
  let currentLine: IntermediateToken[] = [];

  for (const token of tokens) {
    const tokenLines = splitTokenContentByLine(token, new Set(types));
    if (tokenLines.length === 0) {
      continue;
    }

    currentLine.push(...tokenLines[0]);
    if (tokenLines.length > 1) {
      for (let i = 1; i < tokenLines.length; i++) {
        lines.push(currentLine);
        currentLine = tokenLines[i];
      }
    }
  }

  if (currentLine.length > 0) {
    lines.push(currentLine);
  }

  return lines;
};

// Splits a token by newlines encounted inside of its content.
// Returns an array of lines. If the returned array only has a single
// line, no newlines were found.
const splitTokenContentByLine = (
  token: string | Prism.Token,
  types: Set<string> = new Set(['token'])
): IntermediateToken[][] => {
  if (typeof token === 'string') {
    const lines: IntermediateToken[][] = [];
    token.split(/\r?\n/).forEach(line => {
      if (line) {
        lines.push([{types: new Set(types), children: line}]);
      } else {
        // If empty string, new line was at the end of the token
        lines.push([]);
      }
    });
    return lines;
  }

  types.add(token.type);

  if (Array.isArray(token.content)) {
    return splitMultipleTokensByLine(token.content, new Set(types));
  }

  return splitTokenContentByLine(token.content, types);
};

const breakTokensByLine = (
  tokens: Array<string | Prism.Token>
): SyntaxHighlightLine[] => {
  const lines = splitMultipleTokensByLine(tokens);

  return lines.map(line =>
    line.map(token => ({
      children: token.children,
      className: [...token.types].join(' '),
    }))
  );
};

/**
 * Returns a list of tokens broken up by line for syntax highlighting.
 *
 * Meant to be used for code blocks which require custom UI and cannot rely
 * on Prism.highlightElement().
 *
 * Each token contains a `className` and `children` which can be used for
 * rendering like so: <span className={token.className}>{token.children}</span>
 *
 * Automatically handles importing of the language grammar.
 */
export const usePrismTokens = ({
  code,
  language,
}: PrismHighlightParams): SyntaxHighlightLine[] => {
  const [grammar, setGrammar] = useState<Prism.Grammar | null>(() =>
    getPrismGrammar(language)
  );
  useLoadPrismLanguage(language, {
    onLoad: () => {
      setGrammar(getPrismGrammar(language));
    },
  });
  const lines = useMemo(() => {
    if (!grammar) {
      return breakTokensByLine([code]);
    }
    const tokens = Prism.tokenize(code, grammar);
    return breakTokensByLine(tokens);
  }, [grammar, code]);

  return lines;
};
