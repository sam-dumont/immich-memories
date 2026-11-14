import {locale, t} from './i18n.svelte';

const russian = {
  'Use full videos': 'Все видео целиком',
  'Use full video': 'Видео целиком',
  'Start (seconds)': 'Начало (секунды)',
  'End (seconds)': 'Конец (секунды)',
  'Expand the videos in this plan, then choose their start and end.': 'Разверните видео из этого плана целиком, затем выберите начало и конец.',
  'The film follows your ranges, with no total duration limit.': 'Длительность фильма — по вашим отрезкам, без общего ограничения.',
  'Enter a valid time.': 'Введите корректное время.',
  'End must be after start.': 'Конец должен быть позже начала.',
  'The range must fit inside the source video.': 'Диапазон должен находиться в пределах исходного видео.',
  'Save the revision before rendering your ranges.': 'Сохраните версию, чтобы собрать видео с выбранными границами.',
};

export const rangeText = (message: keyof typeof russian) => locale().startsWith('ru') ? russian[message] : t(message);
