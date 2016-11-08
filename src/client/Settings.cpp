//
// Created by Matteo Marescotti on 02/12/15.
//

#include <getopt.h>
#include "lib/Log.h"
#include "Settings.h"


Settings::Settings() :
        server(nullptr),
        lemmas(nullptr) { }

Settings::~Settings() {
    delete this->server;
    delete this->lemmas;
}

void Settings::load_header(std::map<std::string, std::string> &header, char *string) {
    int i;
    for (i = 0; optarg[i] != '=' && optarg[i] != '\0' && i < (uint8_t) -1; i++) { }
    if (optarg[i] != '=') {
        Log::log(Log::ERROR, std::string("bad pair: ") + string);
    }
    optarg[i] = '\0';
    header[std::string(optarg)] = std::string(&optarg[i + 1]);
}


void Settings::load(int argc, char **argv) {
    int opt;
    while ((opt = getopt(argc, argv, "hs:l:r:")) != -1)
        switch (opt) {
            case 'h':
                std::cout << "Usage: " << argv[0] <<
                " [-s server-host:port]"
                        "[-l lemma_server-host:port]"
                        "[-r run-header-key=value [...]]"
                        "\n";
                exit(0);
            case 's':
                this->server = new Address(std::string(optarg));
                break;
            case 'l':
                this->lemmas = new Address(std::string(optarg));
                break;
            case 'r':
                this->load_header(this->header_solve, optarg);
                break;
            default:
                std::cout << "unknown option '" << opt << "'" << "\n";
                exit(-1);
        }
    for (int i = optind; i < argc; i++) {
        this->files.push_back(std::string(argv[i]));
    }
}