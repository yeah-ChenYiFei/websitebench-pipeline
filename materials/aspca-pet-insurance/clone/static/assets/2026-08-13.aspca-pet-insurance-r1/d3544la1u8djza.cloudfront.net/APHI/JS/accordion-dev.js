
function accordion() {
    const accordionConfigProperties = {
       panelHeadingButtons: null,
    }

    const configureAccordionProperties = (accordionProperties) => {
        const { panelHeadingButtons } = accordionProperties;
        accordionConfigProperties.panelHeadingButtons = document.querySelectorAll(`.${panelHeadingButtons}`);
    }

    const isPanelAccordionOpen = (panelButton) => {
      return panelButton.getAttribute("aria-expanded") === 'false' ? true : false;
    }

    const flipCarrotIconUp = (currentCarrotIcon) => {
        currentCarrotIcon.classList.remove("carrot_icon_rotate_down")
        currentCarrotIcon.classList.add("carrot_icon_rotate_up");
    }

    const flipCarrotIconDown = (currentCarrotIcon) => {
        currentCarrotIcon.classList.remove("carrot_icon_rotate_up");
        currentCarrotIcon.classList.add("carrot_icon_rotate_down");
    }

    const flipCarrotIcon = (event) => {
        const panelButton = event.target;
        const currentCarrotIcon = panelButton.querySelector("svg") || panelButton.querySelector("img");

        if (isPanelAccordionOpen(panelButton)) {
            flipCarrotIconUp(currentCarrotIcon);
            return;
        }
        flipCarrotIconDown(currentCarrotIcon);    
    }

    const setAccordionEventsListener = () => {
        const { panelHeadingButtons } = accordionConfigProperties;
        panelHeadingButtons.forEach((panelButton) => {
            panelButton.addEventListener("click", flipCarrotIcon);  
        })
    }

    const innerAccordion = () => {
        return {
            initializeAccordion: (accordionProperties) => {
                configureAccordionProperties(accordionProperties);
                setAccordionEventsListener();
            }
        }
    }
    return innerAccordion();
}


